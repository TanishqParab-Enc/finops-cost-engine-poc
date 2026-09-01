"""Unit tests for the FinOps policy engine - the deterministic gate."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.errors import CostEstimationError
from finops.models import (
    Cloud,
    CostConfidence,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    ResourceCost,
    Status,
)
from finops.policy import engine

from ..conftest import make_config

pytestmark = pytest.mark.unit


def make_estimate(
    *,
    previous: str = "100",
    new: str = "175",
    incremental: str | None = None,
    trust: EstimatorTrust = EstimatorTrust.AUTHORITATIVE,
    currency: str = "USD",
    coverage: CostCoverage | None = None,
    estimator: str = "infracost",
) -> CostEstimate:
    prev = Decimal(previous)
    nxt = Decimal(new)
    return CostEstimate(
        currency=currency,
        estimator=estimator,
        trust=trust,
        previous_monthly_cost=prev,
        new_monthly_cost=nxt,
        incremental_monthly_cost=Decimal(incremental) if incremental is not None else nxt - prev,
        coverage=coverage or CostCoverage(detected_resources=1, supported_resources=1),
    )


class TestThresholdComparison:
    def test_below_threshold_passes(self):
        decision = engine.evaluate(make_estimate(previous="100", new="173"), make_config(threshold=100))
        assert decision.status is Status.PASS
        assert decision.observed_value == Decimal("73")
        assert decision.exceeded_by == Decimal("0")

    def test_above_threshold_fails(self):
        decision = engine.evaluate(make_estimate(previous="100", new="284"), make_config(threshold=100))
        assert decision.status is Status.FAIL
        assert decision.observed_value == Decimal("184")
        assert decision.exceeded_by == Decimal("84")
        assert any("Peer review" in r for r in decision.reasons)

    def test_equal_to_threshold_passes_by_default(self):
        decision = engine.evaluate(make_estimate(previous="0", new="100"), make_config(threshold=100))
        assert decision.status is Status.PASS
        assert "equality passes" in " ".join(decision.reasons)

    def test_equal_to_threshold_fails_when_configured(self):
        config = make_config(threshold=100, equality_is_pass=False)
        decision = engine.evaluate(make_estimate(previous="0", new="100"), config)
        assert decision.status is Status.FAIL
        assert decision.comparison == "<"

    def test_one_cent_over_threshold_fails(self):
        decision = engine.evaluate(make_estimate(previous="0", new="100.01"), make_config(threshold=100))
        assert decision.status is Status.FAIL

    def test_zero_change_passes(self):
        decision = engine.evaluate(make_estimate(previous="100", new="100"), make_config(threshold=100))
        assert decision.status is Status.PASS
        assert decision.observed_value == Decimal("0")


class TestCostReduction:
    def test_reduction_passes(self):
        decision = engine.evaluate(make_estimate(previous="500", new="120"), make_config(threshold=100))
        assert decision.status is Status.PASS
        assert decision.observed_value == Decimal("-380")
        assert "reduces cost" in " ".join(decision.reasons)

    def test_reduction_still_passes_when_flag_disabled(self):
        config = make_config(threshold=100, allow_cost_reductions=False)
        decision = engine.evaluate(make_estimate(previous="500", new="120"), config)
        assert decision.status is Status.PASS


class TestThresholdMetrics:
    def test_annual_metric(self):
        config = make_config(threshold=1000, metric="incremental_annual_cost")
        decision = engine.evaluate(make_estimate(previous="0", new="100"), config)
        assert decision.observed_value == Decimal("1200")
        assert decision.status is Status.FAIL

    def test_total_monthly_cost_metric(self):
        config = make_config(threshold=200, metric="total_monthly_cost")
        decision = engine.evaluate(make_estimate(previous="100", new="175"), config)
        assert decision.observed_value == Decimal("175")
        assert decision.status is Status.PASS

    def test_percentage_metric(self):
        config = make_config(threshold=50, metric="incremental_percentage")
        decision = engine.evaluate(make_estimate(previous="100", new="175"), config)
        assert decision.observed_value == Decimal("75")
        assert decision.status is Status.FAIL

    def test_percentage_with_zero_baseline_and_added_cost_fails(self):
        config = make_config(threshold=50, metric="incremental_percentage")
        decision = engine.evaluate(make_estimate(previous="0", new="10"), config)
        assert decision.status is Status.FAIL

    def test_percentage_with_zero_baseline_and_no_cost_passes(self):
        config = make_config(threshold=50, metric="incremental_percentage")
        decision = engine.evaluate(make_estimate(previous="0", new="0"), config)
        assert decision.status is Status.PASS

    def test_unit_label_reflects_metric(self):
        assert make_config(metric="incremental_annual_cost").threshold.unit == "USD/year"
        assert make_config(metric="incremental_percentage").threshold.unit == "% of baseline"


class TestFailSafe:
    def test_upstream_error_blocks(self):
        decision = engine.evaluate(
            make_estimate(),
            make_config(threshold=100),
            upstream_errors=[CostEstimationError("Infracost unavailable")],
        )
        assert decision.status is Status.ERROR
        assert decision.blocking_errors

    def test_non_authoritative_estimator_blocks(self):
        decision = engine.evaluate(
            make_estimate(trust=EstimatorTrust.NON_AUTHORITATIVE, estimator="mock"),
            make_config(threshold=100),
        )
        assert decision.status is Status.ERROR
        assert "NON_AUTHORITATIVE" in decision.blocking_errors[0]["message"]

    def test_non_authoritative_allowed_when_explicitly_configured(self):
        config = make_config(threshold=100, allow_non_authoritative_lock=True)
        decision = engine.evaluate(
            make_estimate(previous="0", new="10", trust=EstimatorTrust.NON_AUTHORITATIVE), config
        )
        assert decision.status is Status.PASS

    def test_currency_mismatch_blocks(self):
        decision = engine.evaluate(make_estimate(currency="EUR"), make_config(threshold=100))
        assert decision.status is Status.ERROR
        assert "Currency mismatch" in decision.blocking_errors[0]["message"]

    def test_unsupported_resource_warns_by_default(self):
        coverage = CostCoverage(
            detected_resources=2,
            supported_resources=1,
            unsupported_resources=1,
            unsupported_resource_counts={"aws_exotic_thing": 1},
        )
        decision = engine.evaluate(
            make_estimate(previous="0", new="10", coverage=coverage), make_config(threshold=100)
        )
        assert decision.status is Status.PASS

    def test_unsupported_resource_blocks_when_configured(self):
        coverage = CostCoverage(
            detected_resources=2, supported_resources=1, unsupported_resources=1
        )
        config = make_config(threshold=100, on_unsupported_resource="BLOCK")
        decision = engine.evaluate(make_estimate(coverage=coverage), config)
        assert decision.status is Status.ERROR

    def test_no_price_resource_blocks_when_configured(self):
        coverage = CostCoverage(detected_resources=1, no_price_resources=1)
        config = make_config(threshold=100, on_unknown_cost_resource="BLOCK")
        decision = engine.evaluate(make_estimate(coverage=coverage), config)
        assert decision.status is Status.ERROR


class TestTopCostDrivers:
    def test_sorted_by_absolute_delta(self):
        estimate = make_estimate()
        estimate.resources = [
            ResourceCost("a", "aws_instance", Cloud.AWS, Decimal("0"), Decimal("10"), Decimal("10"), CostConfidence.PRICED),
            ResourceCost("b", "aws_instance", Cloud.AWS, Decimal("0"), Decimal("90"), Decimal("90"), CostConfidence.PRICED),
            ResourceCost("c", "aws_instance", Cloud.AWS, Decimal("50"), Decimal("0"), Decimal("-50"), CostConfidence.PRICED),
        ]
        assert [r.address for r in estimate.top_cost_drivers(2)] == ["b", "c"]
