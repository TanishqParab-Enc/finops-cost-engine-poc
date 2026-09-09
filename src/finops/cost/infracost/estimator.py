"""The primary, authoritative cost estimator."""

from __future__ import annotations

import json
from pathlib import Path

from ...models import CostEstimate, EstimatorTrust
from ..base import CostEstimator, EstimationRequest
from .parser import build_estimate, parse_document
from .runner import InfracostRunner


class InfracostEstimator(CostEstimator):
    name = "infracost"
    trust = EstimatorTrust.AUTHORITATIVE

    def __init__(self, runner: InfracostRunner, artifact_dir: Path | None = None) -> None:
        self.runner = runner
        self.artifact_dir = artifact_dir

    def preflight(self) -> None:
        self.runner.preflight()

    def estimate(self, request: EstimationRequest) -> CostEstimate:
        version = self.runner.version()

        proposed_doc = self.runner.scan_plan(request.proposed_plan_json)
        self._persist(proposed_doc, "infracost-proposed.json")
        proposed = parse_document(proposed_doc)

        baseline = None
        if request.baseline_plan_json is not None:
            baseline_doc = self.runner.scan_plan(request.baseline_plan_json)
            self._persist(baseline_doc, "infracost-baseline.json")
            baseline = parse_document(baseline_doc)

        return build_estimate(
            proposed=proposed,
            baseline=baseline,
            estimator=f"infracost ({proposed.schema} schema)",
            estimator_version=version.raw,
            trust=self.trust,
            raw_reference=str(self.artifact_dir) if self.artifact_dir else None,
            plan=request.normalized_plan,
        )

    def _persist(self, document: dict, filename: str) -> None:
        if self.artifact_dir is None:
            return
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / filename).write_text(
            json.dumps(document, indent=2), encoding="utf-8"
        )
