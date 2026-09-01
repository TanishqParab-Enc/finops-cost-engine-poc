"""Replays recorded Infracost JSON so integration tests exercise the real
parser without network access. Still AUTHORITATIVE: the numbers came from a
genuine Infracost run.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import CostEstimationError
from ..models import CostEstimate, EstimatorTrust
from .base import CostEstimator, EstimationRequest
from .infracost.parser import build_estimate, parse_document


class InfracostFixtureEstimator(CostEstimator):
    name = "infracost_fixture"
    trust = EstimatorTrust.AUTHORITATIVE

    def __init__(self, proposed_fixture: Path, baseline_fixture: Path | None = None) -> None:
        self.proposed_fixture = Path(proposed_fixture)
        self.baseline_fixture = Path(baseline_fixture) if baseline_fixture else None

    def preflight(self) -> None:
        if not self.proposed_fixture.is_file():
            raise CostEstimationError(
                f"Infracost fixture not found: {self.proposed_fixture}"
            )

    def estimate(self, request: EstimationRequest) -> CostEstimate:
        self.preflight()
        proposed = parse_document(_load(self.proposed_fixture))
        baseline = (
            parse_document(_load(self.baseline_fixture)) if self.baseline_fixture else None
        )
        return build_estimate(
            proposed=proposed,
            baseline=baseline,
            estimator=f"infracost_fixture ({proposed.schema} schema)",
            estimator_version="recorded",
            trust=self.trust,
            raw_reference=str(self.proposed_fixture),
        )


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CostEstimationError(
            f"Could not read Infracost fixture {path}", detail=str(exc)
        ) from exc
