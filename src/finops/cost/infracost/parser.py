"""Infracost JSON -> cloud-agnostic CostEstimate.

Handles both schemas emitted by the two CLI lines:

* v2 (`infracost scan --json`)      - snake_case, breakdown only
* v0.10 (`infracost breakdown ...`) - camelCase, classic infracost.schema.json

Money values arrive as JSON strings or null. `null` means *Infracost could not
price this*, which is not the same as zero, so it is never coerced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from ...errors import CostEstimationError
from ...models import (
    Action,
    Cloud,
    CostComponent,
    CostConfidence,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    NormalizedPlan,
    ResourceCost,
)
from ...plan.normalizer import detect_cloud

ZERO = Decimal("0")


def _dec(value: Any) -> Decimal | None:
    """Parse an Infracost money/quantity field. None stays None."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


@dataclass
class ParsedResource:
    address: str
    resource_type: str
    monthly_cost: Decimal | None
    components: list[CostComponent] = field(default_factory=list)
    is_supported: bool = True
    is_free: bool = False
    has_usage_based: bool = False
    has_missing_price: bool = False

    @property
    def cloud(self) -> Cloud:
        return detect_cloud(self.resource_type, "")

    def confidence(self) -> CostConfidence:
        if not self.is_supported:
            return CostConfidence.UNSUPPORTED
        if self.has_missing_price:
            return CostConfidence.NO_PRICE
        if self.has_usage_based:
            return CostConfidence.USAGE_BASED
        if self.is_free or (self.monthly_cost is not None and self.monthly_cost == ZERO):
            return CostConfidence.FREE
        return CostConfidence.PRICED


@dataclass
class ParsedBreakdown:
    """One Infracost run, normalised across both schema shapes."""

    currency: str
    total_monthly_cost: Decimal | None
    resources: dict[str, ParsedResource] = field(default_factory=dict)
    coverage: CostCoverage = field(default_factory=CostCoverage)
    schema: str = "unknown"
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------
def detect_schema(document: dict) -> str:
    if not isinstance(document, dict):
        raise CostEstimationError("Infracost output is not a JSON object")
    if "diffTotalMonthlyCost" in document or "totalMonthlyCost" in document:
        return "v0.10"
    if "summary" in document and isinstance(document.get("summary"), dict):
        if "total_monthly_cost" in document["summary"]:
            return "v2"
    if "projects" in document:
        for project in _as_list(document.get("projects")):
            if isinstance(project, dict) and "resources" in project:
                return "v2"
            if isinstance(project, dict) and "breakdown" in project:
                return "v0.10"
    raise CostEstimationError(
        "Unrecognised Infracost JSON schema",
        detail=f"Top-level keys: {sorted(document.keys())[:12]}",
    )


# ---------------------------------------------------------------------------
# v2 parsing (infracost scan --json)
# ---------------------------------------------------------------------------
def _parse_v2_components(node: dict) -> tuple[list[CostComponent], Decimal, bool, bool]:
    """Collect components from a resource and, recursively, its subresources."""
    components: list[CostComponent] = []
    total = ZERO
    usage_based = False
    missing_price = False

    for raw in _as_list(node.get("cost_components")):
        if not isinstance(raw, dict):
            continue
        price = _dec(raw.get("price"))
        quantity = _dec(raw.get("quantity"))
        monthly = _dec(raw.get("total_monthly_cost"))
        usage_cost = _dec(raw.get("usage_monthly_cost")) or ZERO

        if monthly is None or price is None:
            missing_price = True
        else:
            total += monthly
        if usage_cost != ZERO:
            usage_based = True

        components.append(
            CostComponent(
                name=str(raw.get("name") or ""),
                unit=str(raw.get("unit") or ""),
                monthly_quantity=quantity,
                price_per_unit=price,
                monthly_cost=monthly,
                usage_based=usage_cost != ZERO,
                price_not_found=monthly is None or price is None,
            )
        )

    for sub in _as_list(node.get("subresources")):
        if not isinstance(sub, dict):
            continue
        sub_components, sub_total, sub_usage, sub_missing = _parse_v2_components(sub)
        sub_name = str(sub.get("name") or "")
        components.extend(
            CostComponent(
                name=f"{sub_name}: {c.name}" if sub_name else c.name,
                unit=c.unit,
                monthly_quantity=c.monthly_quantity,
                price_per_unit=c.price_per_unit,
                monthly_cost=c.monthly_cost,
                usage_based=c.usage_based,
                price_not_found=c.price_not_found,
            )
            for c in sub_components
        )
        total += sub_total
        usage_based = usage_based or sub_usage
        missing_price = missing_price or sub_missing

    return components, total, usage_based, missing_price


def parse_v2(document: dict) -> ParsedBreakdown:
    summary = _as_dict(document.get("summary"))
    currency = str(document.get("currency") or "USD")
    resources: dict[str, ParsedResource] = {}
    unsupported_counts: dict[str, int] = {}
    no_price_counts: dict[str, int] = {}
    usage_based_total = 0

    for project in _as_list(document.get("projects")):
        if not isinstance(project, dict):
            continue
        for raw in _as_list(project.get("resources")):
            if not isinstance(raw, dict):
                continue
            address = str(raw.get("name") or "")
            if not address:
                continue
            resource_type = str(raw.get("type") or "")
            components, total, usage_based, missing_price = _parse_v2_components(raw)
            is_supported = bool(raw.get("is_supported", True))
            is_free = bool(raw.get("is_free", False))

            if not is_supported and not components:
                unsupported_counts[resource_type] = unsupported_counts.get(resource_type, 0) + 1
            if missing_price:
                no_price_counts[resource_type] = no_price_counts.get(resource_type, 0) + 1
            if usage_based:
                usage_based_total += 1

            # Infracost marks nested blocks unsupported even when priced; only
            # a top-level resource with no priced component is truly uncovered.
            resources[address] = ParsedResource(
                address=address,
                resource_type=resource_type,
                monthly_cost=None if (missing_price and total == ZERO) else total,
                components=components,
                is_supported=is_supported or bool(components),
                is_free=is_free,
                has_usage_based=usage_based,
                has_missing_price=missing_price,
            )

    detected = int(summary.get("resources") or len(resources))
    costed = int(summary.get("costed_resources") or 0)
    free = int(summary.get("free_resources") or 0)
    unsupported = max(sum(unsupported_counts.values()), detected - costed - free)

    coverage = CostCoverage(
        detected_resources=detected,
        supported_resources=costed + free,
        unsupported_resources=max(unsupported, 0),
        no_price_resources=sum(no_price_counts.values()),
        usage_based_resources=usage_based_total,
        unsupported_resource_counts=unsupported_counts,
        no_price_resource_counts=no_price_counts,
    )

    return ParsedBreakdown(
        currency=currency,
        total_monthly_cost=_dec(summary.get("total_monthly_cost")),
        resources=resources,
        coverage=coverage,
        schema="v2",
    )


# ---------------------------------------------------------------------------
# v0.10 parsing (infracost breakdown --format json)
# ---------------------------------------------------------------------------
def _parse_v010_components(node: dict) -> tuple[list[CostComponent], Decimal, bool, bool]:
    components: list[CostComponent] = []
    total = ZERO
    usage_based = False
    missing_price = False

    for raw in _as_list(node.get("costComponents")):
        if not isinstance(raw, dict):
            continue
        price = _dec(raw.get("price"))
        quantity = _dec(raw.get("monthlyQuantity"))
        monthly = _dec(raw.get("monthlyCost"))
        flagged_missing = bool(raw.get("priceNotFound", False)) or monthly is None
        is_usage = bool(raw.get("usageBased", False))

        if monthly is not None:
            total += monthly
        missing_price = missing_price or flagged_missing
        usage_based = usage_based or is_usage

        components.append(
            CostComponent(
                name=str(raw.get("name") or ""),
                unit=str(raw.get("unit") or ""),
                monthly_quantity=quantity,
                price_per_unit=price,
                monthly_cost=monthly,
                usage_based=is_usage,
                price_not_found=flagged_missing,
            )
        )

    for sub in _as_list(node.get("subresources")):
        if not isinstance(sub, dict):
            continue
        sub_components, sub_total, sub_usage, sub_missing = _parse_v010_components(sub)
        sub_name = str(sub.get("name") or "")
        components.extend(
            CostComponent(
                name=f"{sub_name}: {c.name}" if sub_name else c.name,
                unit=c.unit,
                monthly_quantity=c.monthly_quantity,
                price_per_unit=c.price_per_unit,
                monthly_cost=c.monthly_cost,
                usage_based=c.usage_based,
                price_not_found=c.price_not_found,
            )
            for c in sub_components
        )
        total += sub_total
        usage_based = usage_based or sub_usage
        missing_price = missing_price or sub_missing

    return components, total, usage_based, missing_price


def _parse_v010_breakdown_node(node: dict) -> dict[str, ParsedResource]:
    resources: dict[str, ParsedResource] = {}
    for raw in _as_list(node.get("resources")):
        if not isinstance(raw, dict):
            continue
        address = str(raw.get("name") or "")
        if not address:
            continue
        components, total, usage_based, missing_price = _parse_v010_components(raw)
        resources[address] = ParsedResource(
            address=address,
            resource_type=str(raw.get("resourceType") or ""),
            monthly_cost=_dec(raw.get("monthlyCost")) if raw.get("monthlyCost") is not None else total,
            components=components,
            is_supported=True,
            is_free=False,
            has_usage_based=usage_based,
            has_missing_price=missing_price,
        )
    for raw in _as_list(node.get("freeResources")):
        if not isinstance(raw, dict):
            continue
        address = str(raw.get("name") or "")
        if address and address not in resources:
            resources[address] = ParsedResource(
                address=address,
                resource_type=str(raw.get("resourceType") or ""),
                monthly_cost=ZERO,
                is_free=True,
            )
    return resources


def parse_v010(document: dict) -> ParsedBreakdown:
    summary = _as_dict(document.get("summary"))
    resources: dict[str, ParsedResource] = {}
    for project in _as_list(document.get("projects")):
        if not isinstance(project, dict):
            continue
        resources.update(_parse_v010_breakdown_node(_as_dict(project.get("breakdown"))))

    coverage = CostCoverage(
        detected_resources=int(summary.get("totalDetectedResources") or len(resources)),
        supported_resources=int(summary.get("totalSupportedResources") or 0),
        unsupported_resources=int(summary.get("totalUnsupportedResources") or 0),
        no_price_resources=int(summary.get("totalNoPriceResources") or 0),
        usage_based_resources=int(summary.get("totalUsageBasedResources") or 0),
        unsupported_resource_counts=_as_dict(summary.get("unsupportedResourceCounts")),
        no_price_resource_counts=_as_dict(summary.get("noPriceResourceCounts")),
    )

    return ParsedBreakdown(
        currency=str(document.get("currency") or "USD"),
        total_monthly_cost=_dec(document.get("totalMonthlyCost")),
        resources=resources,
        coverage=coverage,
        schema="v0.10",
    )


def parse_document(document: dict) -> ParsedBreakdown:
    schema = detect_schema(document)
    return parse_v2(document) if schema == "v2" else parse_v010(document)


# ---------------------------------------------------------------------------
# Two-run diff -> CostEstimate
# ---------------------------------------------------------------------------
def build_estimate(
    proposed: ParsedBreakdown,
    baseline: ParsedBreakdown | None,
    estimator: str,
    estimator_version: str = "",
    trust: EstimatorTrust = EstimatorTrust.AUTHORITATIVE,
    raw_reference: str | None = None,
    plan: NormalizedPlan | None = None,
) -> CostEstimate:
    """Incremental cost = proposed total - baseline total.

    Verified against CLI v2.16.2: `scan` reports a breakdown only, so the diff
    is computed here rather than read from the tool.

    ``plan`` is the same normalised Terraform plan the gate already parsed -
    optional only for callers with no plan (e.g. a bare fixture). When given,
    its per-address Terraform action (create/update/delete/replace) is
    attached to each ``ResourceCost`` so reporting can label a destroyed
    resource as "destroyed" rather than guessing from the sign of the delta
    alone.
    """
    warnings: list[str] = list(proposed.warnings)
    plan_actions: dict[str, Action] = {c.address: c.action for c in plan.changes} if plan else {}

    if proposed.total_monthly_cost is None:
        raise CostEstimationError(
            "Infracost did not return a total monthly cost for the proposed plan",
            detail="A null total means the change could not be priced; refusing to approve.",
        )

    new_total = proposed.total_monthly_cost

    if baseline is None:
        previous_total = ZERO
        warnings.append(
            "No baseline plan supplied; incremental cost equals the full projected cost."
        )
    elif baseline.total_monthly_cost is None:
        raise CostEstimationError(
            "Infracost did not return a total monthly cost for the baseline plan",
            detail="A null baseline total makes the incremental figure unsafe.",
        )
    else:
        previous_total = baseline.total_monthly_cost
        if baseline.currency != proposed.currency:
            raise CostEstimationError(
                "Baseline and proposed estimates use different currencies",
                detail=f"{baseline.currency} vs {proposed.currency}",
            )

    baseline_resources = baseline.resources if baseline else {}
    addresses = sorted(set(proposed.resources) | set(baseline_resources))

    resource_costs: list[ResourceCost] = []
    for address in addresses:
        new_res = proposed.resources.get(address)
        old_res = baseline_resources.get(address)
        source = new_res or old_res
        if source is None:
            continue

        new_cost = (new_res.monthly_cost or ZERO) if new_res else ZERO
        old_cost = (old_res.monthly_cost or ZERO) if old_res else ZERO
        delta = new_cost - old_cost
        if delta == ZERO and new_cost == ZERO and old_cost == ZERO:
            continue

        resource_costs.append(
            ResourceCost(
                address=address,
                resource_type=source.resource_type,
                cloud=source.cloud,
                previous_monthly_cost=old_cost,
                new_monthly_cost=new_cost,
                delta_monthly_cost=delta,
                confidence=source.confidence(),
                components=(new_res or old_res).components,
                action=plan_actions.get(address),
            )
        )

    coverage = proposed.coverage
    if coverage.unsupported_resources:
        warnings.append(
            f"{coverage.unsupported_resources} resource(s) are not supported by Infracost "
            f"and are excluded from the estimate: {coverage.unsupported_resource_counts}"
        )
    if coverage.no_price_resources:
        warnings.append(
            f"{coverage.no_price_resources} resource(s) had no price available: "
            f"{coverage.no_price_resource_counts}"
        )
    if coverage.usage_based_resources:
        warnings.append(
            f"{coverage.usage_based_resources} usage-based resource(s) are estimated from "
            "usage assumptions; actual cost depends on real consumption."
        )

    return CostEstimate(
        currency=proposed.currency,
        estimator=estimator,
        estimator_version=estimator_version,
        trust=trust,
        previous_monthly_cost=previous_total,
        new_monthly_cost=new_total,
        incremental_monthly_cost=new_total - previous_total,
        resources=resource_costs,
        coverage=coverage,
        warnings=warnings,
        raw_reference=raw_reference,
    )
