"""The CostEstimator port.

Everything downstream (policy, lock, AI, reporting) depends only on this
interface and on `CostEstimate`, never on Infracost specifics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..models import CostEstimate, EstimatorTrust, NormalizedPlan


@dataclass(frozen=True)
class EstimationRequest:
    """A proposed plan, and optionally the baseline it should be compared to.

    When `baseline_plan_json` is None the baseline cost is treated as zero,
    which is correct for a greenfield stack but must be surfaced as a warning.
    """

    proposed_plan_json: Path
    baseline_plan_json: Path | None = None
    normalized_plan: NormalizedPlan | None = None
    currency: str = "USD"


class CostEstimator(ABC):
    name: str = "unknown"
    trust: EstimatorTrust = EstimatorTrust.NON_AUTHORITATIVE

    @abstractmethod
    def estimate(self, request: EstimationRequest) -> CostEstimate:
        """Return a normalised cost estimate or raise CostEstimationError."""

    def preflight(self) -> None:
        """Raise CostEstimationError if the estimator cannot run."""
        return None
