"""Cloud-agnostic domain models shared by every layer of the engine.

Nothing in this module knows about AWS, Azure, GCP, Terraform or any CI/CD
system. The policy engine operates exclusively on these types.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

MONEY_QUANTUM = Decimal("0.01")


def money(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def as_float(value: Decimal | None) -> float | None:
    return None if value is None else float(money(value))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cloud(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    UNKNOWN = "unknown"


class Action(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE = "replace"
    NOOP = "no-op"
    READ = "read"


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class EstimatorTrust(str, Enum):
    """Whether a cost figure may be used to approve a deployment.

    Only AUTHORITATIVE estimates can produce a cost lock. This is enforced in
    ``lock.cost_lock``, so a test double can never gate a real pipeline.
    """

    AUTHORITATIVE = "AUTHORITATIVE"
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"


class CostConfidence(str, Enum):
    """Mirrors the coverage signals Infracost reports per resource."""

    PRICED = "priced"
    FREE = "free"
    USAGE_BASED = "usage_based"
    NO_PRICE = "no_price"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Plan normalisation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResourceChange:
    """One normalised Terraform resource change, provider-agnostic."""

    address: str
    resource_type: str
    name: str
    cloud: Cloud
    action: Action
    provider_name: str = ""
    module_address: str | None = None
    index: Any = None
    region: str | None = None
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)

    @property
    def is_cost_relevant(self) -> bool:
        return self.action in (Action.CREATE, Action.UPDATE, Action.DELETE, Action.REPLACE)

    def to_dict(self) -> dict:
        return {
            "cloud": self.cloud.value,
            "resource": self.resource_type,
            "address": self.address,
            "name": self.name,
            "action": self.action.value,
            "module_address": self.module_address,
            "region": self.region,
        }


@dataclass(frozen=True)
class NormalizedPlan:
    terraform_version: str
    format_version: str
    changes: list[ResourceChange]
    clouds: list[Cloud]
    source_path: str | None = None

    @property
    def cost_relevant_changes(self) -> list[ResourceChange]:
        return [c for c in self.changes if c.is_cost_relevant]

    def fingerprint(self) -> str:
        """Stable hash of the *semantic* change set.

        Binds a cost lock to an exact Terraform change: any edit to the
        infrastructure produces a different fingerprint, so a previously
        approved lock can never be silently reused.
        """
        payload = [
            {
                "address": c.address,
                "type": c.resource_type,
                "cloud": c.cloud.value,
                "action": c.action.value,
                "region": c.region,
                "before": c.before,
                "after": c.after,
            }
            for c in sorted(self.cost_relevant_changes, key=lambda c: c.address)
        ]
        return canonical_hash(payload)

    def to_dict(self) -> dict:
        return {
            "terraform_version": self.terraform_version,
            "format_version": self.format_version,
            "fingerprint": self.fingerprint(),
            "clouds": [c.value for c in self.clouds],
            "changes": [c.to_dict() for c in self.changes],
        }


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CostComponent:
    name: str
    unit: str
    monthly_quantity: Decimal | None
    price_per_unit: Decimal | None
    monthly_cost: Decimal | None
    usage_based: bool = False
    price_not_found: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "unit": self.unit,
            "monthly_quantity": None if self.monthly_quantity is None else float(self.monthly_quantity),
            "price_per_unit": None if self.price_per_unit is None else float(self.price_per_unit),
            "monthly_cost": as_float(self.monthly_cost),
            "usage_based": self.usage_based,
            "price_not_found": self.price_not_found,
        }


@dataclass
class ResourceCost:
    address: str
    resource_type: str
    cloud: Cloud
    previous_monthly_cost: Decimal
    new_monthly_cost: Decimal
    delta_monthly_cost: Decimal
    confidence: CostConfidence
    action: Action | None = None
    components: list[CostComponent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "resource_type": self.resource_type,
            "cloud": self.cloud.value,
            "action": self.action.value if self.action else None,
            "confidence": self.confidence.value,
            "previous_monthly_cost": as_float(self.previous_monthly_cost),
            "new_monthly_cost": as_float(self.new_monthly_cost),
            "delta_monthly_cost": as_float(self.delta_monthly_cost),
            "components": [c.to_dict() for c in self.components],
            "notes": self.notes,
        }


@dataclass
class CostCoverage:
    """Whether the estimate can be trusted to be complete.

    Populated from Infracost's ``summary`` block and per-component flags rather
    than inferred, so the gate never has to guess.
    """

    detected_resources: int = 0
    supported_resources: int = 0
    unsupported_resources: int = 0
    no_price_resources: int = 0
    usage_based_resources: int = 0
    unsupported_resource_counts: dict[str, int] = field(default_factory=dict)
    no_price_resource_counts: dict[str, int] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.unsupported_resources == 0 and self.no_price_resources == 0

    def to_dict(self) -> dict:
        return {
            "detected_resources": self.detected_resources,
            "supported_resources": self.supported_resources,
            "unsupported_resources": self.unsupported_resources,
            "no_price_resources": self.no_price_resources,
            "usage_based_resources": self.usage_based_resources,
            "unsupported_resource_counts": self.unsupported_resource_counts,
            "no_price_resource_counts": self.no_price_resource_counts,
            "is_complete": self.is_complete,
        }


@dataclass
class CostEstimate:
    """Normalised, cloud-agnostic cost result.

    Totals are explicit fields, not sums over ``resources``: Infracost reports
    the authoritative totals (``diffTotalMonthlyCost`` etc.) directly, and
    recomputing them from the resource list would silently drop anything the
    per-resource breakdown does not enumerate.
    """

    currency: str
    estimator: str
    trust: EstimatorTrust
    previous_monthly_cost: Decimal
    new_monthly_cost: Decimal
    incremental_monthly_cost: Decimal
    resources: list[ResourceCost] = field(default_factory=list)
    coverage: CostCoverage = field(default_factory=CostCoverage)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)
    estimator_version: str = ""
    raw_reference: str | None = None

    @property
    def is_authoritative(self) -> bool:
        return self.trust is EstimatorTrust.AUTHORITATIVE

    @property
    def incremental_annual_cost(self) -> Decimal:
        return self.incremental_monthly_cost * 12

    @property
    def incremental_percentage(self) -> Decimal | None:
        """None when there is no baseline to compare against."""
        if self.previous_monthly_cost == 0:
            return None
        return (self.incremental_monthly_cost / self.previous_monthly_cost) * 100

    def top_cost_drivers(self, limit: int = 5) -> list[ResourceCost]:
        return sorted(self.resources, key=lambda r: abs(r.delta_monthly_cost), reverse=True)[:limit]

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "estimator": self.estimator,
            "estimator_version": self.estimator_version,
            "trust": self.trust.value,
            "generated_at": self.generated_at,
            "previous_monthly_cost": as_float(self.previous_monthly_cost),
            "new_monthly_cost": as_float(self.new_monthly_cost),
            "incremental_monthly_cost": as_float(self.incremental_monthly_cost),
            "incremental_annual_cost": as_float(self.incremental_annual_cost),
            "coverage": self.coverage.to_dict(),
            "resources": [r.to_dict() for r in self.resources],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
@dataclass
class PolicyDecision:
    status: Status
    metric: str
    observed_value: Decimal
    threshold_value: Decimal
    currency: str
    comparison: str
    unit: str = "USD/month"
    reasons: list[str] = field(default_factory=list)
    blocking_errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def exceeded_by(self) -> Decimal:
        delta = self.observed_value - self.threshold_value
        return delta if delta > 0 else Decimal("0")

    @property
    def is_pass(self) -> bool:
        return self.status is Status.PASS

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "metric": self.metric,
            "unit": self.unit,
            "observed_value": as_float(self.observed_value),
            "threshold_value": as_float(self.threshold_value),
            "exceeded_by": as_float(self.exceeded_by),
            "currency": self.currency,
            "comparison": self.comparison,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "blocking_errors": self.blocking_errors,
        }


# ---------------------------------------------------------------------------
# AI (explanation only - never authoritative for money)
# ---------------------------------------------------------------------------
@dataclass
class AIAnalysis:
    summary: str
    cost_impact: float
    currency: str
    threshold: float
    decision: str
    reason: str
    cost_drivers: list[str] = field(default_factory=list)
    recommendation: str = ""
    provider: str = "unknown"
    available: bool = True
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "cost_impact": self.cost_impact,
            "currency": self.currency,
            "threshold": self.threshold,
            "decision": self.decision,
            "reason": self.reason,
            "cost_drivers": self.cost_drivers,
            "recommendation": self.recommendation,
            "provider": self.provider,
            "available": self.available,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------
@dataclass
class GateResult:
    status: Status
    decision: PolicyDecision | None = None
    estimate: CostEstimate | None = None
    plan: NormalizedPlan | None = None
    ai: AIAnalysis | None = None
    cost_lock: dict | None = None
    errors: list[dict] = field(default_factory=list)
    execution_id: str = ""
    commit: str = ""
    generated_at: str = field(default_factory=utc_now_iso)

    @property
    def exit_code(self) -> int:
        """0 = PASS, 1 = threshold exceeded, 2 = cannot decide (fail safe)."""
        if self.status is Status.PASS:
            return 0
        if self.status is Status.FAIL:
            return 1
        return 2

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "status": self.status.value,
            "exit_code": self.exit_code,
            "execution_id": self.execution_id,
            "commit": self.commit,
            "generated_at": self.generated_at,
            "plan_fingerprint": self.plan.fingerprint() if self.plan else None,
            "policy": self.decision.to_dict() if self.decision else None,
            "cost": self.estimate.to_dict() if self.estimate else None,
            "ai": self.ai.to_dict() if self.ai else None,
            "cost_lock": self.cost_lock,
            "errors": self.errors,
        }
