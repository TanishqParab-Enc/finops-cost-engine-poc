"""Unit tests for the change-scoped resource cost breakdown: the PR-facing
"Cost breakdown" table must list only resources Terraform is actually taking
an action on for THIS PR - never every priced resource in the deployed
stack, and never inferred merely from a resource costing money."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.models import Action, Cloud, CostConfidence, ResourceCost
from finops.report.breakdown import pr_changed_resources
from finops.report.markdown import render_markdown

from .test_cost_reporting import make_gate_result

pytestmark = pytest.mark.unit


def make_resource(
    *, address: str, action: Action | None, previous: str, new: str
) -> ResourceCost:
    return ResourceCost(
        address=address,
        resource_type="generic_thing",
        cloud=Cloud.AWS,
        previous_monthly_cost=Decimal(previous),
        new_monthly_cost=Decimal(new),
        delta_monthly_cost=Decimal(new) - Decimal(previous),
        confidence=CostConfidence.PRICED,
        action=action,
    )


class TestPrChangedResourcesFiltering:
    def test_zero_change_plan_has_empty_breakdown(self):
        """TEST 1: current > 0, proposed = current, incremental = 0 -
        resource breakdown must be empty even though priced resources exist."""
        resources = [
            make_resource(address=f"generic_thing.{i}", action=Action.NOOP, previous="10", new="10")
            for i in range(5)
        ]
        assert pr_changed_resources_from(resources) == []

    def test_one_resource_change_shows_only_that_resource(self):
        """TEST 2: only the changed resource appears."""
        resources = [
            make_resource(address="module.compute.aws_instance.app", action=Action.UPDATE, previous="0", new="30"),
            *[
                make_resource(address=f"generic_thing.unchanged_{i}", action=Action.NOOP, previous="10", new="10")
                for i in range(39)
            ],
        ]
        result = pr_changed_resources_from(resources)
        assert [r.address for r in result] == ["module.compute.aws_instance.app"]

    def test_multiple_resource_changes_show_only_changed(self):
        """TEST 3: multiple changes - only the changed resources appear."""
        resources = [
            make_resource(address="a.changed_1", action=Action.CREATE, previous="0", new="20"),
            make_resource(address="b.changed_2", action=Action.UPDATE, previous="10", new="15"),
            make_resource(address="c.unchanged", action=Action.NOOP, previous="50", new="50"),
        ]
        result = pr_changed_resources_from(resources)
        assert {r.address for r in result} == {"a.changed_1", "b.changed_2"}

    def test_existing_priced_resource_with_no_action_is_excluded(self):
        """TEST 4: an existing deployed resource with non-zero cost but no
        Terraform action must never appear, however much it costs."""
        resources = [
            make_resource(address="expensive.unchanged", action=Action.NOOP, previous="500", new="500"),
        ]
        assert pr_changed_resources_from(resources) == []

    def test_destroy_shows_only_destroyed_resources_with_negative_delta(self):
        """TEST 5: destroy - only destroyed resources appear, negative
        deltas preserved."""
        resources = [
            make_resource(address="destroyed.a", action=Action.DELETE, previous="96.43", new="0"),
            make_resource(address="untouched.b", action=Action.NOOP, previous="20", new="20"),
        ]
        result = pr_changed_resources_from(resources)
        assert [r.address for r in result] == ["destroyed.a"]
        assert result[0].delta_monthly_cost == Decimal("-96.43")

    def test_mixed_create_destroy_shows_only_affected_resources(self):
        """TEST 6: mixed create/destroy - only affected resources appear."""
        resources = [
            make_resource(address="destroyed.a", action=Action.DELETE, previous="100", new="0"),
            make_resource(address="created.b", action=Action.CREATE, previous="0", new="30"),
            make_resource(address="untouched.c", action=Action.NOOP, previous="40", new="40"),
        ]
        result = pr_changed_resources_from(resources)
        assert {r.address for r in result} == {"destroyed.a", "created.b"}

    def test_no_action_falls_back_to_delta_sign(self):
        """A caller with no plan (action never wired) falls back to the
        delta - existing behaviour for that case is preserved."""
        resources = [
            make_resource(address="no_action.changed", action=None, previous="0", new="10"),
            make_resource(address="no_action.unchanged", action=None, previous="10", new="10"),
        ]
        result = pr_changed_resources_from(resources)
        assert [r.address for r in result] == ["no_action.changed"]


def pr_changed_resources_from(resources: list[ResourceCost]) -> list[ResourceCost]:
    """Adapter: pr_changed_resources takes a CostEstimate, these tests only
    need the resource list, so build a minimal throwaway estimate."""
    from finops.models import CostEstimate, EstimatorTrust

    estimate = CostEstimate(
        currency="USD",
        estimator="test",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal("0"),
        new_monthly_cost=Decimal("0"),
        incremental_monthly_cost=Decimal("0"),
        resources=resources,
    )
    return pr_changed_resources(estimate)


class TestReportOnlyShowsPrChanges:
    def test_zero_change_report_shows_required_no_changes_text(self):
        result = make_gate_result(previous="100", new="100", incremental="0")
        result.estimate.resources = [
            make_resource(address=f"generic_thing.{i}", action=Action.NOOP, previous="20", new="20")
            for i in range(5)
        ]
        markdown = render_markdown(result)

        assert "No infrastructure changes detected." in markdown
        assert "No resource-level incremental cost changes." in markdown
        assert "generic_thing.0" not in markdown

    def test_report_lists_only_the_changed_resource(self):
        result = make_gate_result(previous="0", new="30", incremental="30", threshold="100")
        result.estimate.resources = [
            make_resource(address="module.compute.aws_instance.app", action=Action.CREATE, previous="0", new="30"),
            *[
                make_resource(address=f"generic_thing.unchanged_{i}", action=Action.NOOP, previous="10", new="10")
                for i in range(39)
            ],
        ]
        markdown = render_markdown(result)

        assert "module.compute.aws_instance.app" in markdown
        assert "generic_thing.unchanged_0" not in markdown
        assert "No infrastructure changes detected." not in markdown
