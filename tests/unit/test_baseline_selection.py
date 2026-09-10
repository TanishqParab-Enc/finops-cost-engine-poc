"""Stack-agnostic regression tests for the Cost Gate baseline-selection fix.

These exercise the same `build_estimate` + `policy.engine.evaluate` pipeline
the Cost Gate workflow drives, using a GENERIC stack fixture (never
web-platform, never any real repository stack name) to prove the fix works
for any registered stack, not one hard-coded case.

The bug this guards against: the Cost Gate used to decide "is this stack
deployed?" from whether its Terraform directory existed on the base/main
git ref. A stack can be deployed by an earlier, still-open PR before that
PR merges, so an already-deployed stack absent from base/main was priced as
if its baseline were $0 - the fix instead prices the ACTUAL deployed target
state (via state_json_to_plan_json + the existing Infracost parser),
independent of git history entirely. These tests operate one layer below
the workflow YAML (which cannot be pytest-exercised directly): they prove
that whatever baseline is supplied - however it was obtained - the
downstream cost math and decision are correct.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.cost.infracost.parser import build_estimate, parse_document
from finops.errors import CostEstimationError
from finops.models import Status
from finops.policy import engine

from ..conftest import make_config

pytestmark = pytest.mark.unit

STACK_NAME = "generic-workload"  # deliberately not any real registered stack


def v2_doc(total: str | None, resources: list[dict] | None = None) -> dict:
    return {
        "currency": "USD",
        "summary": {
            "total_monthly_cost": total,
            "resources": len(resources or []),
            "costed_resources": len(resources or []),
            "free_resources": 0,
        },
        "projects": [{"project_name": STACK_NAME, "path": STACK_NAME, "resources": resources or []}],
    }


def v2_resource(name: str, rtype: str, monthly: str) -> dict:
    return {
        "name": name,
        "type": rtype,
        "is_supported": True,
        "is_free": False,
        "cost_components": [
            {
                "name": "usage",
                "unit": "hours",
                "price": "0.1",
                "quantity": "730",
                "total_monthly_cost": monthly,
            }
        ],
        "subresources": [],
    }


class TestFirstDeployment:
    """TEST 1 - no deployed remote state: baseline = 0, normal threshold."""

    def test_no_baseline_supplied_prices_full_cost_as_incremental(self):
        proposed = parse_document(
            v2_doc("250", [v2_resource("generic_thing.a", "generic_thing", "250")])
        )
        estimate = build_estimate(proposed, None, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.previous_monthly_cost == Decimal("0")
        assert estimate.incremental_monthly_cost == Decimal("250")
        assert decision.status is Status.FAIL  # existing threshold behavior, unchanged


class TestAlreadyDeployedNoChange:
    """TEST 2 / TEST 8 - the direct regression: base/main lacks the stack,
    but the deployed target state exists and the PR matches it exactly.
    The baseline must be the real deployed cost, NOT zero."""

    def test_matching_configuration_produces_zero_delta_and_pass(self):
        deployed = parse_document(
            v2_doc("180", [v2_resource("generic_thing.a", "generic_thing", "180")])
        )
        proposed = parse_document(
            v2_doc("180", [v2_resource("generic_thing.a", "generic_thing", "180")])
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.previous_monthly_cost == Decimal("180")  # NOT zero - the bug this fixes
        assert estimate.incremental_monthly_cost == Decimal("0")
        assert decision.status is Status.PASS

    def test_deployed_baseline_is_not_zero_even_though_absent_from_base_ref(self):
        """Explicit proof for TEST 8: nothing about this baseline comes from
        a git ref at all - it is constructed purely from the deployed
        state's own Infracost breakdown."""
        deployed = parse_document(
            v2_doc("180", [v2_resource("generic_thing.a", "generic_thing", "180")])
        )
        proposed = parse_document(
            v2_doc("180", [v2_resource("generic_thing.a", "generic_thing", "180")])
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        assert estimate.previous_monthly_cost != Decimal("0")


class TestAlreadyDeployedSmallIncrease:
    """TEST 3 - already deployed + small increase: normal threshold behavior."""

    def test_small_increase_below_threshold_passes(self):
        deployed = parse_document(
            v2_doc("100", [v2_resource("generic_thing.a", "generic_thing", "100")])
        )
        proposed = parse_document(
            v2_doc("130", [v2_resource("generic_thing.a", "generic_thing", "130")])
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.incremental_monthly_cost == Decimal("30")
        assert decision.status is Status.PASS


class TestAlreadyDeployedLargeIncrease:
    """TEST 4 - already deployed + large increase: BLOCK."""

    def test_large_increase_above_threshold_blocks(self):
        deployed = parse_document(
            v2_doc("100", [v2_resource("generic_thing.a", "generic_thing", "100")])
        )
        proposed = parse_document(
            v2_doc("250", [v2_resource("generic_thing.a", "generic_thing", "250")])
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.incremental_monthly_cost == Decimal("150")
        assert decision.status is Status.FAIL


class TestAlreadyDeployedRemoval:
    """TEST 5 - already deployed + partial removal: negative delta, PASS, savings."""

    def test_partial_removal_passes_with_savings(self):
        deployed = parse_document(
            v2_doc("100", [v2_resource("generic_thing.a", "generic_thing", "100")])
        )
        proposed = parse_document(
            v2_doc("70", [v2_resource("generic_thing.a", "generic_thing", "70")])
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.incremental_monthly_cost == Decimal("-30")
        assert decision.status is Status.PASS
        assert "reduces cost" in " ".join(decision.reasons)


class TestCompleteDestroy:
    """TEST 6 - complete destroy: proposed = 0, negative delta, PASS, savings."""

    def test_full_teardown_passes_with_full_savings(self):
        deployed = parse_document(
            v2_doc("100", [v2_resource("generic_thing.a", "generic_thing", "100")])
        )
        proposed = parse_document(v2_doc("0", []))
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.new_monthly_cost == Decimal("0")
        assert estimate.incremental_monthly_cost == Decimal("-100")
        assert decision.status is Status.PASS


class TestMixedCreateDestroy:
    """TEST 7 - mixed create/destroy: evaluate the NET incremental cost."""

    def test_net_negative_mixed_change_passes(self):
        deployed = parse_document(
            v2_doc(
                "100",
                [v2_resource("generic_thing.destroyed", "generic_thing", "100")],
            )
        )
        proposed = parse_document(
            v2_doc(
                "30",
                [v2_resource("generic_thing.created", "generic_thing", "30")],
            )
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.incremental_monthly_cost == Decimal("-70")
        assert decision.status is Status.PASS

    def test_net_positive_mixed_change_blocks(self):
        deployed = parse_document(
            v2_doc("50", [v2_resource("generic_thing.destroyed", "generic_thing", "50")])
        )
        proposed = parse_document(
            v2_doc("180", [v2_resource("generic_thing.created", "generic_thing", "180")])
        )
        estimate = build_estimate(proposed, deployed, "infracost")
        decision = engine.evaluate(estimate, make_config(threshold=100))

        assert estimate.incremental_monthly_cost == Decimal("130")
        assert decision.status is Status.FAIL


class TestRemoteStateMissing:
    """TEST 9 - remote state genuinely missing: same as first deployment,
    never a fabricated cost."""

    def test_missing_baseline_behaves_like_first_deployment(self):
        proposed = parse_document(
            v2_doc("90", [v2_resource("generic_thing.a", "generic_thing", "90")])
        )
        estimate = build_estimate(proposed, None, "infracost")
        assert estimate.previous_monthly_cost == Decimal("0")
        assert estimate.incremental_monthly_cost == Decimal("90")
        assert any("No baseline" in w for w in estimate.warnings)


class TestMalformedUnknownCost:
    """TEST 10 - malformed/unknown cost: fail-safe, never zero, never PASS."""

    def test_null_total_monthly_cost_raises_rather_than_defaulting_to_zero(self):
        proposed = parse_document(v2_doc(None))
        with pytest.raises(CostEstimationError, match="total monthly cost"):
            build_estimate(proposed, None, "infracost")

    def test_null_baseline_total_raises_rather_than_defaulting_to_zero(self):
        proposed = parse_document(v2_doc("100"))
        deployed = parse_document(v2_doc(None))
        with pytest.raises(CostEstimationError, match="baseline"):
            build_estimate(proposed, deployed, "infracost")
