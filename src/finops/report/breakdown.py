"""Presentation helpers for the resource-level cost breakdown.

Grouping and labelling only - every number comes from the parsed Infracost
result. Nothing here computes a price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import Action, CostConfidence, CostEstimate, ResourceCost, money
from .clouds import service_of as _adapter_service_of

_ACTION_LABEL = {
    Action.CREATE: "added",
    Action.UPDATE: "changed",
    Action.DELETE: "destroyed",
    Action.REPLACE: "replaced",
    Action.NOOP: "unchanged",
    Action.READ: "read",
}

# Only these Terraform actions mean "this change actually touches this
# resource" - NOOP/READ/absent do not, whatever the resource costs.
_PR_CHANGE_ACTIONS = {Action.CREATE, Action.UPDATE, Action.DELETE, Action.REPLACE}


def service_of(resource_type: str) -> str:
    """Delegates to the cloud adapters. AWS labels are unchanged; Azure/GCP no
    longer fall back to the first token of the resource type, which produced
    "Linux" for a VM and "Managed" for a disk."""
    return _adapter_service_of(resource_type)


def change_label(resource: ResourceCost) -> str:
    """The resource's own action when it has one, otherwise the direction of
    the delta.

    A resource whose cost moved is never reported as "unchanged". Terraform
    and Infracost describe infrastructure at different granularities, so the
    action can sit on one resource while the cost lands on another - resizing
    an instance edits a launch template, but the bill moves on the group that
    uses it, which Terraform itself reports as no-op. Labelling that row
    "unchanged" next to a non-zero monthly impact contradicts itself. This is
    decided from the plan's own action and the delta alone, so it holds for
    any such relationship, not one resource pair.
    """
    if resource.action in _PR_CHANGE_ACTIONS:
        return _ACTION_LABEL.get(resource.action, resource.action.value)
    if resource.delta_monthly_cost > 0:
        return "increased"
    if resource.delta_monthly_cost < 0:
        return "decreased"
    if resource.action is not None:
        return _ACTION_LABEL.get(resource.action, resource.action.value)
    return "unchanged"


@dataclass(frozen=True)
class ServiceTotal:
    service: str
    previous_monthly_cost: Decimal
    new_monthly_cost: Decimal
    delta_monthly_cost: Decimal
    resource_count: int

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "previous_monthly_cost": float(self.previous_monthly_cost),
            "new_monthly_cost": float(self.new_monthly_cost),
            "delta_monthly_cost": float(self.delta_monthly_cost),
            "resource_count": self.resource_count,
        }


def service_summary(estimate: CostEstimate) -> list[ServiceTotal]:
    """Per-service rollup, largest projected spend first."""
    buckets: dict[str, list[ResourceCost]] = {}
    for resource in estimate.resources:
        buckets.setdefault(service_of(resource.resource_type), []).append(resource)

    totals = [
        ServiceTotal(
            service=service,
            previous_monthly_cost=money(sum((r.previous_monthly_cost for r in items), Decimal("0"))),
            new_monthly_cost=money(sum((r.new_monthly_cost for r in items), Decimal("0"))),
            delta_monthly_cost=money(sum((r.delta_monthly_cost for r in items), Decimal("0"))),
            resource_count=len(items),
        )
        for service, items in buckets.items()
    ]
    return sorted(totals, key=lambda t: (-t.new_monthly_cost, t.service))


def top_service_drivers(estimate: CostEstimate, limit: int = 5) -> list[ServiceTotal]:
    """Services ranked by actual monthly spend, largest first."""
    return sorted(service_summary(estimate), key=lambda t: -t.new_monthly_cost)[:limit]


# How Infracost classified each resource. Kept explicit so an unpriced resource
# is never silently reported as costing nothing.
#
# NO_PRICE and UNSUPPORTED were previously both rendered as the single label
# "UNSUPPORTED / UNESTIMATED", which made a resource Infracost genuinely
# supports and prices indistinguishable from one it does not support at all.
COVERAGE_LABELS = {
    CostConfidence.PRICED: "PRICED",
    CostConfidence.USAGE_BASED: "USAGE-BASED",
    CostConfidence.FREE: "NO DIRECT CHARGE",
    CostConfidence.NO_PRICE: "UNESTIMATED",
    CostConfidence.UNSUPPORTED: "UNSUPPORTED",
}


def coverage_label(resource: ResourceCost) -> str:
    return COVERAGE_LABELS.get(resource.confidence, resource.confidence.value)


def coverage_breakdown(estimate: CostEstimate) -> dict[str, list[ResourceCost]]:
    """Resources grouped by classification, in reporting order."""
    order = ["PRICED", "USAGE-BASED", "NO DIRECT CHARGE", "UNESTIMATED", "UNSUPPORTED"]
    grouped: dict[str, list[ResourceCost]] = {}
    for resource in estimate.resources:
        grouped.setdefault(coverage_label(resource), []).append(resource)
    return {k: grouped[k] for k in order if k in grouped}


def changed_resources(estimate: CostEstimate) -> list[ResourceCost]:
    return [r for r in estimate.resources if r.delta_monthly_cost != 0]


def is_pr_change(resource: ResourceCost) -> bool:
    """Whether this resource is part of what the change actually does.

    A resource whose cost moved is always in scope. Terraform and Infracost
    describe infrastructure at different granularities: resizing an ASG's
    instances edits `aws_launch_template` (which Infracost does not price)
    while the whole cost delta lands on `aws_autoscaling_group` (which
    Terraform reports as no-op, since the new template version propagates
    without changing the group itself). Requiring the priced resource to
    carry its own Terraform action would drop that delta from the report and
    show "no changes" for a change that demonstrably costs money.

    Otherwise fall back to the plan's action, so a genuine create/delete that
    happens to price at $0 is still listed. An unchanged resource - no cost
    movement and no action - never qualifies, whatever it costs.
    """
    if resource.delta_monthly_cost != 0:
        return True
    if resource.action is not None:
        return resource.action in _PR_CHANGE_ACTIONS
    return False


def pr_changed_resources(estimate: CostEstimate) -> list[ResourceCost]:
    """Resources this PR actually changes, movers first - the whole-stack
    current/proposed/incremental totals stay authoritative and unaffected;
    this only controls which resources the per-resource breakdown lists."""
    changed = [r for r in estimate.resources if is_pr_change(r)]
    return sorted(
        changed,
        key=lambda r: (-abs(r.delta_monthly_cost), -r.new_monthly_cost, r.address),
    )


def ordered_resources(estimate: CostEstimate) -> list[ResourceCost]:
    """Movers first (largest absolute delta), then the rest by projected cost."""
    return sorted(
        estimate.resources,
        key=lambda r: (-abs(r.delta_monthly_cost), -r.new_monthly_cost, r.address),
    )
