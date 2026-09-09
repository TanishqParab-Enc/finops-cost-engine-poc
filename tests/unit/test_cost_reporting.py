"""Unit tests for cost-reduction/destroy reporting semantics: destroyed
resources must be labelled correctly and a PASS caused by savings must be
reported as savings, never mistaken for new spend or for an approval-required
BLOCK."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.models import (
    Action,
    Cloud,
    CostConfidence,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    GateResult,
    PolicyDecision,
    ResourceCost,
    Status,
)
from finops.report.breakdown import change_label
from finops.report.markdown import render_markdown

pytestmark = pytest.mark.unit


def make_resource(*, action: Action | None, delta: str, new: str, previous: str) -> ResourceCost:
    return ResourceCost(
        address="module.thing.aws_thing.x",
        resource_type="aws_thing",
        cloud=Cloud.AWS,
        previous_monthly_cost=Decimal(previous),
        new_monthly_cost=Decimal(new),
        delta_monthly_cost=Decimal(delta),
        confidence=CostConfidence.PRICED,
        action=action,
    )


class TestChangeLabel:
    def test_destroyed_resource_labelled_destroyed(self):
        resource = make_resource(action=Action.DELETE, delta="-96.43", new="0", previous="96.43")
        assert change_label(resource) == "destroyed"

    def test_created_resource_labelled_added(self):
        resource = make_resource(action=Action.CREATE, delta="96.43", new="96.43", previous="0")
        assert change_label(resource) == "added"

    def test_no_action_falls_back_to_delta_sign(self):
        resource = make_resource(action=None, delta="-10", new="0", previous="10")
        assert change_label(resource) == "decreased"


def make_gate_result(*, previous: str, new: str, incremental: str, threshold: str = "100") -> GateResult:
    estimate = CostEstimate(
        currency="USD",
        estimator="infracost (v2 schema)",
        estimator_version="2.16.2",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal(previous),
        new_monthly_cost=Decimal(new),
        incremental_monthly_cost=Decimal(incremental),
        resources=[],
        coverage=CostCoverage(detected_resources=1, supported_resources=1),
    )
    decision = PolicyDecision(
        status=Status.PASS if Decimal(incremental) <= Decimal(threshold) else Status.FAIL,
        metric="incremental_monthly_cost",
        observed_value=Decimal(incremental),
        threshold_value=Decimal(threshold),
        currency="USD",
        comparison="<=",
    )
    if decision.status is Status.PASS and Decimal(incremental) < 0:
        decision.reasons.append(f"Change reduces cost by {abs(Decimal(incremental))} USD/month; below threshold by definition.")
    return GateResult(status=decision.status, decision=decision, estimate=estimate, cost_lock={"lock_id": "l1", "plan_fingerprint": "f1"})


class TestNegativeDeltaReporting:
    def test_full_teardown_report_shows_savings_pass_and_no_approval(self):
        result = make_gate_result(previous="259.02", new="0", incremental="-259.02")
        markdown = render_markdown(result)

        assert "Cost Reduction Detected" in markdown
        assert "Cost reduction detected" in markdown
        assert "| **Monthly cost impact** | **USD -259.02** |" in markdown
        assert "| **Monthly savings** | **USD 259.02** |" in markdown
        assert "**PASS**" in markdown
        assert "Peer review" not in markdown
        assert "Peer approval required" not in markdown

    def test_reduction_pass_never_shows_the_generic_locked_spend_message(self):
        """'Cost has been locked for this CI/CD execution.' reads as new spend
        was approved - a savings-only PASS must never show it."""
        result = make_gate_result(previous="259.02", new="0", incremental="-259.02")
        markdown = render_markdown(result)
        assert "Cost has been locked for this CI/CD execution." not in markdown
        assert (
            "This savings has been locked to the exact reviewed plan so the deployment "
            "can proceed - no additional spend was approved or requires review."
        ) in markdown

    def test_reduction_pass_still_reports_the_real_lock_identifiers(self):
        """The underlying lock is real (needed to authorise the destroy's own
        Terraform apply) - only the misleading wording changes, not the lock."""
        result = make_gate_result(previous="259.02", new="0", incremental="-259.02")
        markdown = render_markdown(result)
        assert "`lock_id: l1`" in markdown
        assert "`plan_fingerprint: f1`" in markdown

    def test_negative_impact_sign_is_never_dropped_or_flipped(self):
        result = make_gate_result(previous="259.02", new="0", incremental="-259.02")
        markdown = render_markdown(result)
        assert "USD -259.02" in markdown  # the impact row keeps its minus sign
        assert "USD 259.02" in markdown  # the unsigned savings figure also appears

    def test_positive_pass_below_threshold_has_no_savings_or_reduction_banner(self):
        result = make_gate_result(previous="0", new="50", incremental="50")
        markdown = render_markdown(result)
        assert "Monthly savings" not in markdown
        assert "Cost reduction detected" not in markdown
        assert "**PASS**" in markdown

    def test_positive_pass_keeps_the_original_locked_spend_message_unchanged(self):
        """Positive-cost PASS lock messaging must not change at all."""
        result = make_gate_result(previous="0", new="50", incremental="50")
        markdown = render_markdown(result)
        assert "Cost has been locked for this CI/CD execution." in markdown
        assert "`lock_id: l1`" in markdown

    def test_block_report_unchanged_by_this_feature(self):
        result = make_gate_result(previous="0", new="259.02", incremental="259.02")
        markdown = render_markdown(result)
        assert "**FAIL**" in markdown
        assert "Peer review is required" in markdown  # existing BLOCK behavior, untouched
        assert "`FINOPS: BLOCKED`" in markdown
        assert "Monthly savings" not in markdown
        assert "Cost reduction detected" not in markdown

