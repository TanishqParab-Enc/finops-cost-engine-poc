"""Component F - the deterministic FinOps gate.

Operates only on `CostEstimate` and `ThresholdConfig`. It has no knowledge of
Terraform, Infracost, AWS, Azure, GCP or any CI/CD system, so the business rule
can be changed without touching any provider code.
"""

from __future__ import annotations

from decimal import Decimal

from ..config import Config
from ..errors import FinOpsError, PolicyError
from ..models import CostEstimate, PolicyDecision, Status

ZERO = Decimal("0")


def _observed_value(estimate: CostEstimate, metric: str) -> Decimal:
    if metric == "incremental_monthly_cost":
        return estimate.incremental_monthly_cost
    if metric == "incremental_annual_cost":
        return estimate.incremental_annual_cost
    if metric == "total_monthly_cost":
        return estimate.new_monthly_cost
    if metric == "incremental_percentage":
        percentage = estimate.incremental_percentage
        if percentage is None:
            # No baseline: any added cost is an infinite relative increase.
            return ZERO if estimate.incremental_monthly_cost <= ZERO else Decimal("Infinity")
        return percentage
    raise PolicyError(f"Unsupported threshold metric '{metric}'")


def evaluate(
    estimate: CostEstimate,
    config: Config,
    upstream_errors: list[FinOpsError] | None = None,
) -> PolicyDecision:
    threshold = config.threshold
    fail_safe = config.fail_safe

    decision = PolicyDecision(
        status=Status.PASS,
        metric=threshold.metric,
        observed_value=ZERO,
        threshold_value=threshold.value,
        currency=threshold.currency,
        comparison=threshold.comparison,
        unit=threshold.unit,
    )

    for error in upstream_errors or []:
        decision.blocking_errors.append(error.to_dict())

    if decision.blocking_errors:
        decision.status = Status.ERROR
        decision.reasons.append(
            "Cost could not be established; failing safe rather than approving."
        )
        return decision

    # A test double must never gate a real pipeline.
    if not estimate.is_authoritative and not config.cost_estimation.allow_non_authoritative_lock:
        decision.status = Status.ERROR
        decision.blocking_errors.append(
            {
                "category": "COST_ESTIMATION",
                "message": f"Estimator '{estimate.estimator}' is NON_AUTHORITATIVE",
                "detail": "Set cost_estimation.allow_non_authoritative_lock to override (testing only).",
            }
        )
        decision.reasons.append("Refusing to gate on a non-authoritative cost estimate.")
        return decision

    if estimate.currency != threshold.currency:
        decision.status = Status.ERROR
        decision.blocking_errors.append(
            {
                "category": "CONFIGURATION",
                "message": "Currency mismatch between estimate and threshold",
                "detail": f"estimate={estimate.currency} threshold={threshold.currency}",
            }
        )
        return decision

    coverage = estimate.coverage
    if coverage.unsupported_resources and fail_safe.blocks("on_unsupported_resource"):
        decision.status = Status.ERROR
        decision.blocking_errors.append(
            {
                "category": "COST_ESTIMATION",
                "message": f"{coverage.unsupported_resources} unsupported resource(s)",
                "detail": str(coverage.unsupported_resource_counts),
            }
        )
        return decision

    if coverage.no_price_resources and fail_safe.blocks("on_unknown_cost_resource"):
        decision.status = Status.ERROR
        decision.blocking_errors.append(
            {
                "category": "COST_ESTIMATION",
                "message": f"{coverage.no_price_resources} resource(s) with no available price",
                "detail": str(coverage.no_price_resource_counts),
            }
        )
        return decision

    decision.warnings.extend(estimate.warnings)

    observed = _observed_value(estimate, threshold.metric)
    decision.observed_value = observed

    if threshold.allow_cost_reductions and observed < ZERO:
        decision.status = Status.PASS
        decision.reasons.append(
            f"Change reduces cost by {abs(observed)} {decision.unit}; below threshold by definition."
        )
        return decision

    within = observed <= threshold.value if threshold.equality_is_pass else observed < threshold.value

    if within:
        decision.status = Status.PASS
        equality_note = " (equality passes)" if observed == threshold.value else ""
        decision.reasons.append(
            f"Estimated {threshold.metric} of {observed} is within the configured "
            f"threshold of {threshold.value} {decision.unit}{equality_note}."
        )
    else:
        decision.status = Status.FAIL
        decision.reasons.append(
            f"Estimated {threshold.metric} of {observed} exceeds the configured "
            f"threshold of {threshold.value} {decision.unit} by {decision.exceeded_by}."
        )
        decision.reasons.append("Peer review is required before this change can proceed.")

    return decision
