"""Deterministic test double. NOT AUTHORITATIVE.

Exists so unit and end-to-end tests can exercise the policy engine, cost lock,
AI layer and CLI without an Infracost binary, API key or network. It must never
be used to approve a real deployment: `lock.cost_lock` refuses to write an
approval artifact from a NON_AUTHORITATIVE estimate unless explicitly allowed.
"""

from __future__ import annotations

from decimal import Decimal

from ..models import (
    Cloud,
    CostConfidence,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    ResourceCost,
)
from ..plan.normalizer import detect_cloud
from .base import CostEstimator, EstimationRequest

WARNING = "Mock estimator - not valid for cost approval"

HOURS_PER_MONTH = Decimal("730")

# Illustrative only. Never treat these as real prices.
_HOURLY: dict[str, str] = {
    "t3.micro": "0.0104",
    "t3.medium": "0.0416",
    "m5.large": "0.096",
    "m5.xlarge": "0.192",
    "m5.2xlarge": "0.384",
    "Standard_B2s": "0.0416",
    "Standard_D2s_v5": "0.096",
    "Standard_D8s_v5": "0.384",
    "e2-medium": "0.033503",
    "n2-standard-2": "0.097118",
    "n2-standard-8": "0.388472",
}

_SIZE_KEYS = ("instance_type", "vm_size", "machine_type", "size", "sku_name")


def _monthly_cost(attributes: dict) -> Decimal:
    for key in _SIZE_KEYS:
        value = attributes.get(key)
        if isinstance(value, str) and value in _HOURLY:
            return Decimal(_HOURLY[value]) * HOURS_PER_MONTH
    return Decimal("0")


class MockEstimator(CostEstimator):
    name = "mock"
    trust = EstimatorTrust.NON_AUTHORITATIVE

    def estimate(self, request: EstimationRequest) -> CostEstimate:
        plan = request.normalized_plan
        resources: list[ResourceCost] = []
        previous = Decimal("0")
        new = Decimal("0")

        for change in (plan.cost_relevant_changes if plan else []):
            before = _monthly_cost(change.before)
            after = _monthly_cost(change.after)
            previous += before
            new += after
            if before == 0 and after == 0:
                continue
            resources.append(
                ResourceCost(
                    address=change.address,
                    resource_type=change.resource_type,
                    cloud=change.cloud or detect_cloud(change.resource_type),
                    action=change.action,
                    previous_monthly_cost=before,
                    new_monthly_cost=after,
                    delta_monthly_cost=after - before,
                    confidence=CostConfidence.PRICED,
                    notes=[WARNING],
                )
            )

        return CostEstimate(
            currency=request.currency,
            estimator=self.name,
            estimator_version="test-double",
            trust=self.trust,
            previous_monthly_cost=previous,
            new_monthly_cost=new,
            incremental_monthly_cost=new - previous,
            resources=resources,
            coverage=CostCoverage(
                detected_resources=len(plan.cost_relevant_changes) if plan else 0,
                supported_resources=len(resources),
            ),
            warnings=[WARNING],
        )


__all__ = ["MockEstimator", "Cloud", "WARNING"]
