"""Convert a bare `terraform show -json` STATE document (no plan file
argument - i.e. the ACTUAL currently deployed state, not a plan/diff) into
the minimal plan-shaped JSON Infracost's CLI already understands.

Infracost always prices a plan's *proposed/after* configuration - pricing any
Terraform config against real state still prices "cost after applying that
config", never "what genuinely exists today", regardless of which state the
plan started from. Reading the state directly and reshaping it is the only
way to get Infracost's own pricing of what is actually deployed right now,
independent of a pull request's proposed changes.

This is a faithful reshape, not a fabrication: Terraform's plan JSON and its
bare state JSON share the same per-resource schema (address/type/name/
provider_name/values/...) one level down - only the top-level key differs
(`values` for state, `planned_values` for a plan). No cost, price, action or
resource is invented; every attribute comes straight from Terraform itself.
"""

from __future__ import annotations

from typing import Any

from ..errors import PlanError


def state_json_to_plan_json(state_document: dict[str, Any]) -> dict[str, Any]:
    """Reshape a `terraform show -json` state document into a minimal
    plan-shaped document Infracost's `scan`/`breakdown` commands accept.

    An empty/absent `values` (a stack with no deployed state yet) reshapes
    into an empty `planned_values`, which Infracost correctly prices as
    $0 - the same outcome a genuine first deployment already gets.
    """
    if not isinstance(state_document, dict):
        raise PlanError(
            "Not a valid `terraform show -json` state document",
            detail=f"Expected a JSON object, got {type(state_document).__name__}",
        )
    if "planned_values" in state_document or "resource_changes" in state_document:
        raise PlanError(
            "This is a plan document, not a bare state document",
            detail=(
                "state_json_to_plan_json expects the output of "
                "`terraform show -json` with no plan file argument."
            ),
        )
    values = state_document.get("values") or {"root_module": {}}
    return {
        "format_version": state_document.get("format_version", "1.2"),
        "terraform_version": state_document.get("terraform_version", ""),
        "planned_values": values,
        "resource_changes": [],
        "configuration": {},
    }
