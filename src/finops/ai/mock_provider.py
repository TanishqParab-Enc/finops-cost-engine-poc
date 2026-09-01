"""Deterministic offline provider.

Produces a genuinely useful explanation from the cost data without any network
call, so the POC is fully demonstrable and testable with no AI credentials.
"""

from __future__ import annotations

import json
from typing import Any

from .base import AIProvider


def _fmt(value: Any, currency: str) -> str:
    return f"{currency} {value:,.2f}" if isinstance(value, (int, float)) else str(value)


class MockAIProvider(AIProvider):
    name = "mock"

    def analyze_raw(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        context = json.loads(user_prompt)
        cost = context["authoritative_cost_estimate"]
        policy = context["policy_decision"]
        change = context["infrastructure_change"]

        currency = cost["currency"]
        incremental = cost["incremental_monthly_cost"] or 0.0
        clouds = ", ".join(change.get("clouds") or ["unknown"]) or "unknown"
        count = change.get("total_changes", 0)
        drivers = cost.get("top_cost_drivers") or []

        actions: dict[str, int] = {}
        for item in change.get("changes", []):
            actions[item["action"]] = actions.get(item["action"], 0) + 1
        action_text = ", ".join(f"{n} {a}" for a, n in sorted(actions.items())) or "no changes"

        direction = "increase" if incremental > 0 else ("reduction" if incremental < 0 else "no change")
        summary = (
            f"This pull request changes {count} billable resource(s) across {clouds} "
            f"({action_text}). Infracost estimates a monthly cost {direction} of "
            f"{_fmt(abs(incremental), currency)}, moving the stack from "
            f"{_fmt(cost['previous_monthly_cost'], currency)} to "
            f"{_fmt(cost['new_monthly_cost'], currency)} per month."
        )

        if policy["status"] == "FAIL":
            reason = (
                f"The estimated {policy['metric']} of {policy['observed_value']} exceeds the "
                f"configured threshold of {policy['threshold_value']} {policy['unit']} by "
                f"{policy['exceeded_by']}. The build is blocked and peer review is required."
            )
        elif policy["status"] == "PASS":
            reason = (
                f"The estimated {policy['metric']} of {policy['observed_value']} is within the "
                f"configured threshold of {policy['threshold_value']} {policy['unit']} "
                f"(comparison '{policy['comparison']}'), so the cost is approved and locked "
                f"for this CI/CD execution."
            )
        else:
            reason = (
                "The cost could not be established with confidence, so the pipeline fails "
                "safe rather than approving the change."
            )

        cost_drivers = [
            f"{d['address']} ({d['resource_type']}, {d['cloud']}): "
            f"{_fmt(d['delta_monthly_cost'], currency)}/month"
            for d in drivers
            if d.get("delta_monthly_cost")
        ] or ["No individually priced resource dominates this change."]

        if incremental <= 0:
            recommendation = "No action needed; this change does not increase spend."
        elif drivers:
            top = drivers[0]
            recommendation = (
                f"The largest contributor is {top['address']}. Consider right-sizing it, "
                "adopting a cheaper instance family or committed-use pricing, or scoping the "
                "change to a lower environment first."
            )
        else:
            recommendation = "Review whether every new resource is required in this environment."

        warnings = cost.get("coverage_warnings") or []
        if warnings:
            recommendation += (
                " Note that the estimate has coverage caveats: " + "; ".join(warnings[:2])
            )

        return {
            "summary": summary,
            "reason": reason,
            "cost_drivers": cost_drivers[:10],
            "recommendation": recommendation,
        }
