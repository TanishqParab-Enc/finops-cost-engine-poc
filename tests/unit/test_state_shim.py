"""Unit tests for state_json_to_plan_json - the read-only reshape that turns
a bare `terraform show -json` STATE document (no plan argument) into the
plan-shaped JSON Infracost's CLI already understands, so the Cost Gate can
price whatever is ACTUALLY deployed for a stack, independent of git history."""

from __future__ import annotations

import pytest

from finops.errors import PlanError
from finops.plan.state_shim import state_json_to_plan_json

pytestmark = pytest.mark.unit


def _state_doc(resources: list[dict] | None = None) -> dict:
    return {
        "format_version": "1.2",
        "terraform_version": "1.11.0",
        "values": {"root_module": {"resources": resources or []}},
    }


class TestStateJsonToPlanJson:
    def test_reshapes_values_into_planned_values(self):
        resource = {
            "address": "aws_instance.example",
            "mode": "managed",
            "type": "aws_instance",
            "name": "example",
            "provider_name": "registry.terraform.io/hashicorp/aws",
            "values": {"instance_type": "t3.large"},
        }
        plan_doc = state_json_to_plan_json(_state_doc([resource]))

        assert plan_doc["planned_values"]["root_module"]["resources"] == [resource]
        assert plan_doc["resource_changes"] == []
        assert "configuration" in plan_doc

    def test_no_resources_in_no_change_are_not_invented(self):
        """A resource is never invented - an empty state stays empty."""
        plan_doc = state_json_to_plan_json(_state_doc([]))
        assert plan_doc["planned_values"]["root_module"]["resources"] == []

    def test_absent_values_key_reshapes_to_empty_root_module(self):
        """A genuinely empty/never-deployed state has no 'values' key at
        all - this must reshape to zero resources, not raise or fabricate."""
        state_doc = {"format_version": "1.2", "terraform_version": "1.11.0"}
        plan_doc = state_json_to_plan_json(state_doc)
        assert plan_doc["planned_values"] == {"root_module": {}}

    def test_rejects_a_plan_document_passed_by_mistake(self):
        """Passing an actual PLAN (planned_values/resource_changes already
        present) instead of a bare STATE document must fail loudly, not
        silently double-reshape or misprice."""
        with pytest.raises(PlanError, match="plan document"):
            state_json_to_plan_json(
                {"format_version": "1.2", "planned_values": {}, "resource_changes": []}
            )

    def test_rejects_non_object_input(self):
        with pytest.raises(PlanError, match="valid"):
            state_json_to_plan_json(["not", "an", "object"])  # type: ignore[arg-type]

    def test_preserves_format_and_terraform_version(self):
        plan_doc = state_json_to_plan_json(_state_doc([]))
        assert plan_doc["format_version"] == "1.2"
        assert plan_doc["terraform_version"] == "1.11.0"
