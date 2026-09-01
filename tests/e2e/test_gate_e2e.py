"""End-to-end tests for the full CI/CD gate.

Scenario 1: below threshold -> PASS -> cost lock created -> pipeline continues.
Scenario 2: above threshold -> FAIL -> no cost lock -> pipeline stops.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from finops.cost.fixture_estimator import InfracostFixtureEstimator
from finops.cost.mock_estimator import MockEstimator
from finops.gate import GateRequest, run_gate, write_artifacts
from finops.lock.cost_lock import LOCK_FILENAME, verify_cost_lock
from finops.models import Status
from finops.plan.normalizer import normalize_plan_file
from finops.report.markdown import render_markdown

from ..conftest import make_config

pytestmark = pytest.mark.e2e

CLOUDS = ["aws", "azure", "gcp"]


def gate(cloud, scenario, plans_dir, fixtures_dir, tmp_path, **config_kwargs):
    config = make_config(output_dir=str(tmp_path / ".finops"), **config_kwargs)
    estimator = InfracostFixtureEstimator(
        proposed_fixture=fixtures_dir / f"{cloud}-{scenario}.json",
        baseline_fixture=fixtures_dir / f"{cloud}-baseline.json",
    )
    result = run_gate(
        GateRequest(
            proposed_plan=plans_dir / f"{cloud}-{scenario}.json",
            baseline_plan=plans_dir / f"{cloud}-baseline.json",
            commit=f"commit-{cloud}-{scenario}",
            execution_id=f"run-{cloud}-{scenario}",
        ),
        config,
        estimator,
    )
    return result, config


class TestScenario1BelowThreshold:
    @pytest.mark.parametrize("cloud", CLOUDS)
    def test_passes_and_locks_cost(self, cloud, plans_dir, infracost_fixtures, tmp_path):
        result, config = gate(cloud, "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)

        assert result.status is Status.PASS
        assert result.exit_code == 0
        assert result.cost_lock is not None
        assert result.cost_lock["status"] == "APPROVED"
        assert result.decision.exceeded_by == Decimal("0")

    @pytest.mark.parametrize("cloud", CLOUDS)
    def test_lock_file_written_and_verifies(self, cloud, plans_dir, infracost_fixtures, tmp_path):
        result, config = gate(cloud, "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)

        lock_path = Path(config.cost_lock.output_dir) / LOCK_FILENAME
        assert lock_path.is_file()

        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        plan = normalize_plan_file(plans_dir / f"{cloud}-pass.json")
        assert verify_cost_lock(lock, plan, config) == []

    @pytest.mark.parametrize("cloud", CLOUDS)
    def test_lock_records_the_approved_estimate(self, cloud, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate(cloud, "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        lock = result.cost_lock
        assert lock["estimated_incremental_monthly_cost"] == pytest.approx(
            float(result.estimate.incremental_monthly_cost), abs=0.01
        )
        assert lock["threshold"] == 100.0
        assert lock["estimator_trust"] == "AUTHORITATIVE"
        assert lock["commit"] == f"commit-{cloud}-pass"
        assert lock["execution_id"] == f"run-{cloud}-pass"

    def test_pr_comment_reports_pass(self, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        markdown = render_markdown(result)
        assert "FinOps Cost Check Passed" in markdown
        assert "Cost has been locked for this CI/CD execution." in markdown
        assert "AUTHORITATIVE" in markdown


class TestScenario2AboveThreshold:
    @pytest.mark.parametrize("cloud", CLOUDS)
    def test_fails_and_creates_no_lock(self, cloud, plans_dir, infracost_fixtures, tmp_path):
        result, config = gate(cloud, "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)

        assert result.status is Status.FAIL
        assert result.exit_code == 1
        assert result.cost_lock is None
        assert not (Path(config.cost_lock.output_dir) / LOCK_FILENAME).exists()

    @pytest.mark.parametrize("cloud", CLOUDS)
    def test_reports_amount_exceeded(self, cloud, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate(cloud, "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        assert result.decision.exceeded_by > 0
        assert any("Peer review" in r for r in result.decision.reasons)

    def test_pr_comment_reports_failure(self, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate("aws", "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        markdown = render_markdown(result)
        assert "FinOps Cost Check Failed" in markdown
        assert "Peer review is required" in markdown
        assert "No cost lock was created" in markdown


class TestEdgeCases:
    def test_cost_exactly_equal_to_threshold_passes(self, plans_dir, infracost_fixtures, tmp_path):
        probe, _ = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        exact = probe.estimate.incremental_monthly_cost

        result, _ = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=exact)
        assert result.status is Status.PASS
        assert result.cost_lock is not None

    def test_cost_one_cent_over_threshold_fails(self, plans_dir, infracost_fixtures, tmp_path):
        probe, _ = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        just_under = probe.estimate.incremental_monthly_cost - Decimal("0.01")

        result, _ = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=just_under)
        assert result.status is Status.FAIL
        assert result.cost_lock is None

    def test_cost_reduction_passes(self, plans_dir, infracost_fixtures, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100)
        estimator = InfracostFixtureEstimator(
            proposed_fixture=infracost_fixtures / "aws-baseline.json",
            baseline_fixture=infracost_fixtures / "aws-fail.json",
        )
        result = run_gate(
            GateRequest(proposed_plan=plans_dir / "aws-baseline.json", commit="c", execution_id="e"),
            config,
            estimator,
        )
        assert result.status is Status.PASS
        assert result.estimate.incremental_monthly_cost < 0
        assert result.cost_lock is not None

    def test_multiple_resources_in_one_pr(self, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate("aws", "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        assert len(result.plan.cost_relevant_changes) > 1
        assert len(result.estimate.resources) > 1

    def test_missing_plan_file_is_error_not_approval(self, tmp_path, infracost_fixtures):
        config = make_config(output_dir=str(tmp_path / ".finops"))
        estimator = InfracostFixtureEstimator(infracost_fixtures / "aws-pass.json")
        result = run_gate(GateRequest(proposed_plan=tmp_path / "nope.json"), config, estimator)

        assert result.status is Status.ERROR
        assert result.exit_code == 2
        assert result.cost_lock is None
        assert result.errors[0]["category"] == "INFRASTRUCTURE_VALIDATION"

    def test_estimation_failure_is_error_not_approval(self, plans_dir, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"))
        estimator = InfracostFixtureEstimator(tmp_path / "missing-fixture.json")
        result = run_gate(
            GateRequest(proposed_plan=plans_dir / "aws-pass.json"), config, estimator
        )

        assert result.status is Status.ERROR
        assert result.exit_code == 2
        assert result.cost_lock is None
        assert result.errors[0]["category"] == "COST_ESTIMATION"

    def test_mock_estimator_cannot_approve(self, plans_dir, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100000)
        result = run_gate(
            GateRequest(proposed_plan=plans_dir / "aws-pass.json"), config, MockEstimator()
        )

        assert result.status is Status.ERROR
        assert result.cost_lock is None
        assert "NON_AUTHORITATIVE" in json.dumps(result.errors)

    def test_mock_estimator_can_approve_only_when_explicitly_allowed(self, plans_dir, tmp_path):
        config = make_config(
            output_dir=str(tmp_path / ".finops"),
            threshold=100000,
            allow_non_authoritative_lock=True,
        )
        result = run_gate(
            GateRequest(proposed_plan=plans_dir / "aws-pass.json"), config, MockEstimator()
        )
        assert result.status is Status.PASS
        assert result.cost_lock["estimator_trust"] == "NON_AUTHORITATIVE"


class TestAIIsAdvisoryOnly:
    def test_ai_failure_does_not_change_a_pass(self, plans_dir, infracost_fixtures, tmp_path, monkeypatch):
        import finops.ai.factory as factory

        monkeypatch.setattr(
            factory, "build_provider", lambda _c: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        result, _ = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)

        assert result.status is Status.PASS
        assert result.cost_lock is not None
        assert result.ai.available is False

    def test_ai_failure_does_not_change_a_fail(self, plans_dir, infracost_fixtures, tmp_path, monkeypatch):
        import finops.ai.factory as factory

        monkeypatch.setattr(
            factory, "build_provider", lambda _c: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        result, _ = gate("aws", "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)

        assert result.status is Status.FAIL
        assert result.cost_lock is None

    def test_ai_cannot_override_monetary_values(self, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate("aws", "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        assert result.ai.cost_impact == pytest.approx(
            float(result.decision.observed_value), abs=0.01
        )
        assert result.ai.threshold == 100.0

    def test_ai_disabled_still_produces_a_decision(self, plans_dir, infracost_fixtures, tmp_path):
        result, _ = gate(
            "aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100, ai_enabled=False
        )
        assert result.status is Status.PASS
        assert result.ai.available is False


class TestArtifacts:
    def test_all_artifacts_written(self, plans_dir, infracost_fixtures, tmp_path):
        result, config = gate("gcp", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        written = write_artifacts(result, config)

        assert set(written) == {"result", "comment", "cost", "plan"}
        for path in written.values():
            assert path.is_file() and path.stat().st_size > 0

        payload = json.loads(written["result"].read_text(encoding="utf-8"))
        assert payload["status"] == "PASS"
        assert payload["exit_code"] == 0
        assert payload["plan_fingerprint"].startswith("sha256:")

    def test_result_json_is_machine_readable(self, plans_dir, infracost_fixtures, tmp_path):
        result, config = gate("aws", "fail", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        payload = json.loads(json.dumps(result.to_dict()))
        assert payload["policy"]["status"] == "FAIL"
        assert payload["cost"]["incremental_monthly_cost"] > 100
        assert payload["cost_lock"] is None


class TestLockInvalidation:
    def test_lock_from_pass_scenario_rejected_against_fail_plan(
        self, plans_dir, infracost_fixtures, tmp_path
    ):
        result, config = gate("aws", "pass", plans_dir, infracost_fixtures, tmp_path, threshold=100)
        changed_plan = normalize_plan_file(plans_dir / "aws-fail.json")

        problems = verify_cost_lock(result.cost_lock, changed_plan, config)
        assert any("modified since approval" in p for p in problems)
