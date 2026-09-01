"""AI provider port and prompt construction."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ..models import (
    AIAnalysis,
    CostEstimate,
    NormalizedPlan,
    PolicyDecision,
    as_float,
)
from ..plan.sanitizer import sanitize_plan

SYSTEM_PROMPT = """You are a FinOps analyst reviewing a Terraform pull request.

You are given (1) a sanitised summary of the infrastructure change and (2) an
AUTHORITATIVE cost estimate already produced by Infracost, plus the policy
decision already made by a deterministic rules engine.

Your job is ONLY to explain. You must not compute, recalculate, contradict or
restate different monetary figures. Treat every number you are given as fact.

Respond with a single JSON object and nothing else:
{
  "summary": "2-3 sentences on what changed and its cost impact",
  "reason": "why the change passed or failed the threshold",
  "cost_drivers": ["most expensive contributors, most significant first"],
  "recommendation": "concrete, actionable optimisation advice"
}
"""


def build_prompt_context(
    plan: NormalizedPlan,
    estimate: CostEstimate,
    decision: PolicyDecision,
    max_resources: int = 40,
) -> dict[str, Any]:
    return {
        "infrastructure_change": sanitize_plan(plan, max_resources=max_resources),
        "authoritative_cost_estimate": {
            "source": estimate.estimator,
            "currency": estimate.currency,
            "previous_monthly_cost": as_float(estimate.previous_monthly_cost),
            "new_monthly_cost": as_float(estimate.new_monthly_cost),
            "incremental_monthly_cost": as_float(estimate.incremental_monthly_cost),
            "top_cost_drivers": [
                {
                    "address": r.address,
                    "resource_type": r.resource_type,
                    "cloud": r.cloud.value,
                    "delta_monthly_cost": as_float(r.delta_monthly_cost),
                    "confidence": r.confidence.value,
                }
                for r in estimate.top_cost_drivers()
            ],
            "coverage_warnings": estimate.warnings,
        },
        "policy_decision": {
            "status": decision.status.value,
            "metric": decision.metric,
            "unit": decision.unit,
            "observed_value": as_float(decision.observed_value),
            "threshold_value": as_float(decision.threshold_value),
            "exceeded_by": as_float(decision.exceeded_by),
            "comparison": decision.comparison,
        },
    }


def build_user_prompt(context: dict[str, Any]) -> str:
    return json.dumps(context, indent=2)


class AIProvider(ABC):
    name = "unknown"

    @abstractmethod
    def analyze_raw(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return the parsed JSON object from the model, or raise AIError."""

    def analyze(
        self,
        plan: NormalizedPlan,
        estimate: CostEstimate,
        decision: PolicyDecision,
        max_resources: int = 40,
    ) -> AIAnalysis:
        from .schema import validate_analysis

        context = build_prompt_context(plan, estimate, decision, max_resources)
        payload = validate_analysis(self.analyze_raw(SYSTEM_PROMPT, build_user_prompt(context)))

        # Monetary fields come from the deterministic result, never the model.
        return AIAnalysis(
            summary=payload["summary"],
            cost_impact=as_float(decision.observed_value) or 0.0,
            currency=estimate.currency,
            threshold=as_float(decision.threshold_value) or 0.0,
            decision="BLOCK" if decision.status.value == "FAIL" else "ALLOW",
            reason=payload["reason"],
            cost_drivers=payload.get("cost_drivers", []),
            recommendation=payload.get("recommendation", ""),
            provider=self.name,
            available=True,
        )
