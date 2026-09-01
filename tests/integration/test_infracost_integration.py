"""Integration tests: real Terraform plan JSON -> real Infracost JSON -> CostEstimate.

These replay golden fixtures captured from genuine Infracost runs
(scripts/capture_fixtures.py), so the authoritative code path is covered with no
network access and no API key.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.cost.base import EstimationRequest
from finops.cost.fixture_estimator import InfracostFixtureEstimator
from finops.models import Cloud, EstimatorTrust, Status
from finops.plan.normalizer import normalize_plan_file
from finops.policy import engine

from ..conftest import make_config

pytestmark = pytest.mark.integration

CLOUDS = [
    pytest.param("aws", Cloud.AWS, id="aws"),
    pytest.param("azure", Cloud.AZURE, id="azure"),
    pytest.param("gcp", Cloud.GCP, id="gcp"),
]


def estimate_for(cloud: str, scenario: str, plans_dir, fixtures_dir):
    estimator = InfracostFixtureEstimator(
        proposed_fixture=fixtures_dir / f"{cloud}-{scenario}.json",
        baseline_fixture=fixtures_dir / f"{cloud}-baseline.json",
    )
    plan = normalize_plan_file(plans_dir / f"{cloud}-{scenario}.json")
    return plan, estimator.estimate(
        EstimationRequest(
            proposed_plan_json=plans_dir / f"{cloud}-{scenario}.json",
            baseline_plan_json=plans_dir / f"{cloud}-baseline.json",
            normalized_plan=plan,
        )
    )


class TestFixturesExist:
    @pytest.mark.parametrize("cloud,_expected", CLOUDS)
    @pytest.mark.parametrize("scenario", ["baseline", "pass", "fail"])
    def test_golden_fixture_and_plan_present(self, cloud, _expected, scenario, plans_dir, infracost_fixtures):
        assert (infracost_fixtures / f"{cloud}-{scenario}.json").is_file()
        assert (plans_dir / f"{cloud}-{scenario}.json").is_file()


class TestMultiCloudEstimation:
    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_pass_scenario_is_priced(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        plan, estimate = estimate_for(cloud, "pass", plans_dir, infracost_fixtures)
        assert plan.clouds == [expected_cloud]
        assert estimate.trust is EstimatorTrust.AUTHORITATIVE
        assert estimate.currency == "USD"
        assert estimate.previous_monthly_cost > 0
        assert estimate.new_monthly_cost > estimate.previous_monthly_cost
        assert estimate.incremental_monthly_cost > 0

    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_fail_scenario_costs_more_than_pass(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        _, passing = estimate_for(cloud, "pass", plans_dir, infracost_fixtures)
        _, failing = estimate_for(cloud, "fail", plans_dir, infracost_fixtures)
        assert failing.incremental_monthly_cost > passing.incremental_monthly_cost

    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_incremental_equals_new_minus_previous(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        _, estimate = estimate_for(cloud, "fail", plans_dir, infracost_fixtures)
        assert estimate.incremental_monthly_cost == (
            estimate.new_monthly_cost - estimate.previous_monthly_cost
        )

    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_resources_tagged_with_correct_cloud(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        _, estimate = estimate_for(cloud, "fail", plans_dir, infracost_fixtures)
        assert estimate.resources
        assert {r.cloud for r in estimate.resources} == {expected_cloud}

    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_baseline_against_itself_is_zero(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        estimator = InfracostFixtureEstimator(
            proposed_fixture=infracost_fixtures / f"{cloud}-baseline.json",
            baseline_fixture=infracost_fixtures / f"{cloud}-baseline.json",
        )
        estimate = estimator.estimate(
            EstimationRequest(proposed_plan_json=plans_dir / f"{cloud}-baseline.json")
        )
        assert estimate.incremental_monthly_cost == Decimal("0")


class TestKnownCosts:
    """Pin the actual prices Infracost returned, so a regression is visible."""

    @pytest.mark.parametrize(
        "cloud,previous,new",
        [
            ("aws", "9.192", "74.08"),
            ("azure", "9.992", "74.88"),
            ("gcp", "26.4591683", "61.716912"),
        ],
    )
    def test_pass_scenario_totals(self, cloud, previous, new, plans_dir, infracost_fixtures):
        _, estimate = estimate_for(cloud, "pass", plans_dir, infracost_fixtures)
        assert estimate.previous_monthly_cost == Decimal(previous)
        assert estimate.new_monthly_cost == Decimal(new)


class TestPolicyAcrossClouds:
    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_pass_scenario_passes_threshold(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        _, estimate = estimate_for(cloud, "pass", plans_dir, infracost_fixtures)
        decision = engine.evaluate(estimate, make_config(threshold=100))
        assert decision.status is Status.PASS

    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_fail_scenario_fails_threshold(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        _, estimate = estimate_for(cloud, "fail", plans_dir, infracost_fixtures)
        decision = engine.evaluate(estimate, make_config(threshold=100))
        assert decision.status is Status.FAIL
        assert decision.exceeded_by > 0

    @pytest.mark.parametrize("cloud,expected_cloud", CLOUDS)
    def test_generous_threshold_lets_fail_scenario_pass(self, cloud, expected_cloud, plans_dir, infracost_fixtures):
        _, estimate = estimate_for(cloud, "fail", plans_dir, infracost_fixtures)
        decision = engine.evaluate(estimate, make_config(threshold=10000))
        assert decision.status is Status.PASS

    def test_threshold_is_the_only_thing_that_changes_the_outcome(self, plans_dir, infracost_fixtures):
        _, estimate = estimate_for("aws", "pass", plans_dir, infracost_fixtures)
        observed = estimate.incremental_monthly_cost
        just_under = engine.evaluate(estimate, make_config(threshold=observed))
        just_over = engine.evaluate(estimate, make_config(threshold=observed - Decimal("0.01")))
        assert just_under.status is Status.PASS
        assert just_over.status is Status.FAIL
