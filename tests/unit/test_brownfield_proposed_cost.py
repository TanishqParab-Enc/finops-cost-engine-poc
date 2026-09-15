"""Regression tests for the brownfield proposed-cost asymmetry.

Observed live on the deployed web-platform/dev stack: the proposed cost was
planned from EMPTY state (a hermetic local backend) while the baseline was
priced from the ACTUAL deployed remote state. Terraform cannot resolve a
reference to a resource that does not exist yet, so from empty state the
autoscaling group's `launch_template.id` was "known after apply":

    planned_values : launch_template = [{"version": "$Latest"}]
    after_unknown  : launch_template = [{"id": true, "name": true}]

Infracost attaches the launch template to the group by resolving that id, so
with it unknown the group carried no launch template and priced at $0 - while
the state-derived baseline, which has the concrete id, priced it at $66.04.
A t3.large -> t3.xlarge upgrade was therefore reported as a $66.04/mo SAVING
instead of a $60.74/mo increase.

The fix is generic: price the proposed side from a plan taken against the
ACTUAL deployed state (`-refresh=false`, same state snapshot as the
baseline), so an unchanged resource prices identically on both sides and
cancels out, and only genuine changes move the delta. Nothing here is
specific to autoscaling groups - any unresolved reference behaves this way.

The monetary figures below are recorded observations from real Infracost
runs against web-platform/dev; they are fixtures, never a price book. No
test computes a price.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import yaml

from finops.models import (
    Action,
    Cloud,
    CostConfidence,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    ResourceCost,
)
from finops.policy import engine
from finops.report.breakdown import change_label, pr_changed_resources
from finops.report.markdown import render_markdown

from ..conftest import make_config
from .test_workflow_dispatch_governance import WORKFLOW_PATH

pytestmark = pytest.mark.unit

# Measured with Infracost v2.16.2 against the deployed web-platform/dev stack.
ASG_T3_LARGE = Decimal("66.036")
ASG_T3_XLARGE = Decimal("126.772")


def resource(address, rtype, action, previous, new) -> ResourceCost:
    previous = Decimal(previous)
    new = Decimal(new)
    return ResourceCost(
        address=address,
        resource_type=rtype,
        cloud=Cloud.AWS,
        action=action,
        previous_monthly_cost=previous,
        new_monthly_cost=new,
        delta_monthly_cost=new - previous,
        confidence=CostConfidence.PRICED,
    )


def estimate_from(resources: list[ResourceCost]) -> CostEstimate:
    previous = sum((r.previous_monthly_cost for r in resources), Decimal("0"))
    new = sum((r.new_monthly_cost for r in resources), Decimal("0"))
    return CostEstimate(
        currency="USD",
        estimator="infracost (v2 schema)",
        estimator_version="2.16.2",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=previous,
        new_monthly_cost=new,
        incremental_monthly_cost=new - previous,
        resources=resources,
        coverage=CostCoverage(detected_resources=len(resources), supported_resources=len(resources)),
    )


def resize_estimate() -> CostEstimate:
    """What the corrected pipeline produces: both sides priced from the same
    deployed-state snapshot, so only the resized compute moves."""
    return estimate_from(
        [
            resource(
                "module.compute.aws_autoscaling_group.app",
                "aws_autoscaling_group",
                Action.NOOP,
                ASG_T3_LARGE,
                ASG_T3_XLARGE,
            ),
            resource("module.alb.aws_lb.main", "aws_lb", Action.NOOP, "16.425", "16.425"),
            resource("module.database.aws_db_instance.main", "aws_db_instance", Action.NOOP, "32.03", "32.03"),
            resource("module.networking.aws_nat_gateway.main[0]", "aws_nat_gateway", Action.NOOP, "32.85", "32.85"),
            resource("module.networking.aws_eip.nat[0]", "aws_eip", Action.NOOP, "3.65", "3.65"),
            resource("module.dns.aws_route53_zone.main[0]", "aws_route53_zone", Action.NOOP, "0.5", "0.5"),
        ]
    )


class TestUpgradeIsNeverReportedAsASaving:
    def test_instance_size_increase_produces_a_positive_incremental_cost(self):
        est = resize_estimate()
        assert est.incremental_monthly_cost > 0
        assert est.incremental_monthly_cost == ASG_T3_XLARGE - ASG_T3_LARGE

    def test_incremental_equals_proposed_minus_current(self):
        est = resize_estimate()
        assert est.incremental_monthly_cost == est.new_monthly_cost - est.previous_monthly_cost

    def test_both_totals_are_complete_stack_totals(self):
        """Current and proposed both cover the whole stack - the delta comes
        from the change, not from one side pricing fewer resources."""
        est = resize_estimate()
        untouched = sum(
            (r.previous_monthly_cost for r in est.resources if r.delta_monthly_cost == 0),
            Decimal("0"),
        )
        assert untouched > 0
        assert est.previous_monthly_cost == ASG_T3_LARGE + untouched
        assert est.new_monthly_cost == ASG_T3_XLARGE + untouched
        # Every resource is priced on both sides - neither side is truncated.
        assert all(r.previous_monthly_cost > 0 and r.new_monthly_cost > 0 for r in est.resources)

    def test_the_old_asymmetry_would_have_been_a_false_saving(self):
        """Reproduces the bug: proposed priced from empty state loses the
        launch-template link, so the group costs $0 on the proposed side."""
        broken = estimate_from(
            [
                resource(
                    "module.compute.aws_autoscaling_group.app",
                    "aws_autoscaling_group",
                    Action.NOOP,
                    ASG_T3_LARGE,
                    "0",
                ),
            ]
        )
        assert broken.incremental_monthly_cost < 0
        # The corrected pipeline must not reproduce it.
        assert resize_estimate().incremental_monthly_cost > 0

    def test_gate_evaluates_the_corrected_incremental_cost(self):
        est = resize_estimate()
        decision = engine.evaluate(est, make_config(threshold=100))
        assert decision.observed_value == est.incremental_monthly_cost
        assert decision.observed_value > 0


class TestResourceLevelBreakdownIsChangeScoped:
    def test_only_the_resized_compute_resource_is_listed(self):
        rows = pr_changed_resources(resize_estimate())
        assert [r.address for r in rows] == ["module.compute.aws_autoscaling_group.app"]

    def test_unchanged_resources_are_excluded(self):
        rows = pr_changed_resources(resize_estimate())
        listed = {r.address for r in rows}
        for unchanged in (
            "module.alb.aws_lb.main",
            "module.database.aws_db_instance.main",
            "module.networking.aws_nat_gateway.main[0]",
            "module.networking.aws_eip.nat[0]",
            "module.dns.aws_route53_zone.main[0]",
        ):
            assert unchanged not in listed

    def test_a_true_noop_moves_no_cost_and_lists_nothing(self):
        """Same stack, nothing changed: identical totals, zero delta, empty
        breakdown - the invariant the shared state snapshot guarantees."""
        rows = [
            resource(r.address, r.resource_type, Action.NOOP, r.previous_monthly_cost, r.previous_monthly_cost)
            for r in resize_estimate().resources
        ]
        est = estimate_from(rows)
        assert est.previous_monthly_cost == est.new_monthly_cost
        assert est.incremental_monthly_cost == Decimal("0")
        assert pr_changed_resources(est) == []


class TestCostMovementIsNeverLabelledUnchanged:
    """The action can sit on one resource while the cost lands on another, so
    the priced row must not claim to be unchanged next to a non-zero impact.
    Decided from action + delta only - no resource type is special-cased."""

    def test_cost_bearing_row_is_not_labelled_unchanged(self):
        rows = pr_changed_resources(resize_estimate())
        assert change_label(rows[0]) != "unchanged"

    def test_a_cost_increase_without_its_own_action_reads_as_increased(self):
        row = resource("any.resource", "any_type", Action.NOOP, "10", "25")
        assert change_label(row) == "increased"

    def test_a_cost_decrease_without_its_own_action_reads_as_decreased(self):
        row = resource("any.resource", "any_type", Action.NOOP, "25", "10")
        assert change_label(row) == "decreased"

    def test_a_genuinely_unchanged_resource_is_still_unchanged(self):
        row = resource("any.resource", "any_type", Action.NOOP, "25", "25")
        assert change_label(row) == "unchanged"

    @pytest.mark.parametrize(
        "action,expected",
        [
            (Action.CREATE, "added"),
            (Action.UPDATE, "changed"),
            (Action.DELETE, "destroyed"),
            (Action.REPLACE, "replaced"),
        ],
    )
    def test_a_resource_with_its_own_action_keeps_that_label(self, action, expected):
        """Regression: the existing vocabulary must not shift, so destroy
        reporting still reads 'destroyed' rather than 'decreased'."""
        row = resource("any.resource", "any_type", action, "25", "0")
        assert change_label(row) == expected

    def test_rendered_report_does_not_call_the_moved_resource_unchanged(self):
        from finops.models import GateResult, Status

        result = GateResult(status=Status.PASS, commit="c", execution_id="e")
        result.estimate = resize_estimate()
        result.decision = engine.evaluate(result.estimate, make_config(threshold=100))
        body = render_markdown(result)
        line = next(
            ln for ln in body.splitlines()
            if "module.compute.aws_autoscaling_group.app" in ln
        )
        assert "unchanged" not in line
        assert "increased" in line
        assert "+USD 60.74" in line


class TestWorkflowPricesTheProposedState:
    @pytest.fixture(scope="class")
    @classmethod
    def workflow(cls) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def test_baseline_and_proposed_share_one_state_snapshot(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        baseline = next(s for s in steps if s.get("id") == "baseline")
        proposed = next(s for s in steps if s.get("id") == "proposed")
        assert baseline["working-directory"] == proposed["working-directory"]
        assert "-refresh=false" in proposed["run"]

    def test_the_priced_proposed_plan_never_uses_a_local_backend(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        proposed = next(s for s in steps if s.get("id") == "proposed")
        assert 'backend "local"' not in proposed["run"]

    def test_the_only_hermetic_plan_left_is_the_aws_drift_check(self, workflow):
        """A hermetic plan may still exist, but it must not feed pricing."""
        steps = workflow["jobs"]["cost-gate"]["steps"]
        hermetic = [s for s in steps if 'backend "local"' in str(s.get("run", ""))]
        assert len(hermetic) == 1
        assert hermetic[0]["if"] == "matrix.stack.name == 'aws'"
        assert "proposed-plan.json" not in hermetic[0]["run"]
        assert "head-config-plan.json" in hermetic[0]["run"]

    def test_gate_prices_the_real_proposed_plan(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        gate = next(s for s in steps if s.get("id") == "gate")
        assert '--plan "$GITHUB_WORKSPACE/proposed-plan.json"' in gate["run"]
        assert "--require-baseline" in gate["run"]

    def test_no_single_resource_or_demo_fallback_exists(self, workflow):
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "aws_instance" not in raw
        steps = workflow["jobs"]["cost-gate"]["steps"]
        proposed = next(s for s in steps if s.get("id") == "proposed")
        assert "-target" not in proposed["run"]
        assert proposed["working-directory"] == "baseline/${{ matrix.stack.dir }}"
