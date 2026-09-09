"""Deterministic reconciliation of the resource breakdown against Infracost.

The breakdown is an observability layer. Infracost's own totals stay
authoritative - see the note on ``CostEstimate``. This module only asks whether
the per-resource numbers *add up to* those totals, so a reporting bug is
visible instead of quietly misrepresenting the bill.

Nothing here can change a decision. Reconciliation produces findings; the
policy engine never reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import CostEstimate, money

# Infracost rounds each resource independently, so a handful of cents of drift
# across a large plan is expected and is not a defect.
DEFAULT_TOLERANCE = Decimal("0.05")


@dataclass(frozen=True)
class Reconciliation:
    label: str
    authoritative: Decimal
    summed: Decimal
    tolerance: Decimal
    enumerated_resources: int
    complete_coverage: bool

    @property
    def difference(self) -> Decimal:
        return money(self.summed - self.authoritative)

    @property
    def ok(self) -> bool:
        return abs(self.difference) <= self.tolerance

    @property
    def explained_by_coverage(self) -> bool:
        """A gap is expected when Infracost did not enumerate every resource."""
        return not self.ok and not self.complete_coverage

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "authoritative": float(self.authoritative),
            "summed": float(self.summed),
            "difference": float(self.difference),
            "tolerance": float(self.tolerance),
            "ok": self.ok,
            "enumerated_resources": self.enumerated_resources,
            "complete_coverage": self.complete_coverage,
            "explained_by_coverage": self.explained_by_coverage,
        }

    def message(self, currency: str) -> str:
        if self.ok:
            return (
                f"{self.label}: resource breakdown sums to {currency} {self.summed} "
                f"and matches the authoritative Infracost total."
            )
        base = (
            f"{self.label}: resource breakdown sums to {currency} {self.summed} but "
            f"Infracost reports {currency} {self.authoritative} "
            f"(difference {currency} {self.difference})."
        )
        if self.explained_by_coverage:
            return base + " Infracost did not price every resource, so the breakdown is incomplete by design."
        return base + " This is a reporting defect; the Infracost total above remains authoritative."


def _sum(values) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return money(total)


def reconcile_estimate(
    estimate: CostEstimate, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Reconciliation]:
    complete = estimate.coverage.is_complete
    count = len(estimate.resources)
    return [
        Reconciliation(
            label="total monthly cost",
            authoritative=money(estimate.new_monthly_cost),
            summed=_sum(r.new_monthly_cost for r in estimate.resources),
            tolerance=tolerance,
            enumerated_resources=count,
            complete_coverage=complete,
        ),
        Reconciliation(
            label="incremental monthly cost",
            authoritative=money(estimate.incremental_monthly_cost),
            summed=_sum(r.delta_monthly_cost for r in estimate.resources),
            tolerance=tolerance,
            enumerated_resources=count,
            complete_coverage=complete,
        ),
    ]


def reconciliation_problems(results: list[Reconciliation]) -> list[str]:
    """Only genuine reporting defects - gaps Infracost itself declared are excluded."""
    return [r.label for r in results if not r.ok and not r.explained_by_coverage]
