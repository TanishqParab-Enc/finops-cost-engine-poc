"""Deterministic join of Terraform plan facts to Infracost money.

Terraform and Infracost are joined on the Terraform resource address only -
never on display or service name, which are not stable identities.

`ResourceCost` is deliberately left untouched. It remains the sole carrier of
cost, confidence and components, so every existing total, reconciliation and
policy decision is computed from exactly the same values as before. This module
only attaches plan-derived configuration alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..models import Action, Cloud, CostEstimate, NormalizedPlan, ResourceChange, ResourceCost
from .clouds import extract_configuration, service_of
from .metadata import configuration_delta


def _normalize_address(address: str) -> str:
    return (address or "").strip().lower()


@dataclass(frozen=True)
class ResourceView:
    """One resource as the report sees it: Infracost money plus plan facts."""

    cost: ResourceCost
    change: ResourceChange | None
    service: str
    configuration: dict[str, str] = field(default_factory=dict)
    before_configuration: dict[str, str] = field(default_factory=dict)
    changed_fields: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)

    # -- identity / money passthrough. Values are never recomputed here. ----
    @property
    def address(self) -> str:
        return self.cost.address

    @property
    def resource_type(self) -> str:
        return self.cost.resource_type

    @property
    def cloud(self) -> Cloud:
        return self.cost.cloud

    @property
    def action(self) -> Action | None:
        return self.cost.action

    @property
    def previous_monthly_cost(self) -> Decimal:
        return self.cost.previous_monthly_cost

    @property
    def new_monthly_cost(self) -> Decimal:
        return self.cost.new_monthly_cost

    @property
    def delta_monthly_cost(self) -> Decimal:
        return self.cost.delta_monthly_cost

    @property
    def has_configuration(self) -> bool:
        return bool(self.configuration or self.before_configuration)

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "resource_type": self.resource_type,
            "cloud": self.cloud.value,
            "service": self.service,
            "action": self.action.value if self.action else None,
            "configuration": dict(self.configuration),
            "before_configuration": dict(self.before_configuration),
            "changed_fields": {
                label: {"before": old, "after": new}
                for label, (old, new) in self.changed_fields.items()
            },
        }


def _index_changes(plan: NormalizedPlan | None) -> dict[str, ResourceChange]:
    if plan is None:
        return {}
    return {_normalize_address(c.address): c for c in plan.changes if c.address}


def build_view(cost: ResourceCost, change: ResourceChange | None) -> ResourceView:
    """Attach plan configuration to one priced resource.

    A resource Infracost priced but Terraform did not report (or vice versa)
    still produces a view - it simply carries no configuration, which is
    reported honestly rather than guessed.
    """
    cloud = cost.cloud if cost.cloud != Cloud.UNKNOWN else (change.cloud if change else None)
    service = service_of(cost.resource_type, cloud)

    if change is None:
        return ResourceView(cost=cost, change=None, service=service)

    after = extract_configuration(change.resource_type, change.after, cloud)
    before = extract_configuration(change.resource_type, change.before, cloud)

    # A delete has no "after", so its declared configuration is what existed.
    current = after or (before if change.action is Action.DELETE else {})
    changed = configuration_delta(before, after) if before and after else {}

    return ResourceView(
        cost=cost,
        change=change,
        service=service,
        configuration=current,
        before_configuration=before,
        changed_fields=changed,
    )


def join_estimate_with_plan(
    estimate: CostEstimate,
    plan: NormalizedPlan | None,
) -> list[ResourceView]:
    """Every priced resource, in the estimate's own order, with plan facts."""
    changes = _index_changes(plan)
    return [
        build_view(cost, changes.get(_normalize_address(cost.address)))
        for cost in estimate.resources
    ]


def views_by_address(views: list[ResourceView]) -> dict[str, ResourceView]:
    return {view.address: view for view in views}
