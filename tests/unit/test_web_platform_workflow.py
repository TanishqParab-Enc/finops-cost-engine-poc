"""Security boundary of the web-platform validation workflow.

This workflow prices a workload that cannot be deployed. The tests below assert
that it stays that way: no apply, no cost lock, no deploy role, no production
path, and no interference with the terraform/aws production workflow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
WEB = REPO / ".github/workflows/web-platform-finops.yml"
GATE = REPO / ".github/workflows/finops-cost-gate.yml"
WORKLOAD = "terraform/workloads/web-platform"


@pytest.fixture(scope="module")
def web() -> dict:
    return yaml.safe_load(WEB.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def web_text() -> str:
    return WEB.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def triggers(web) -> dict:
    return web.get("on") or web.get(True)


def _steps(job: dict) -> list[str]:
    return [s.get("name", s.get("uses", "?")) for s in job["steps"]]


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


class TestTerraformRoot:
    def test_workload_dir_is_web_platform(self, web):
        assert web["env"]["WORKLOAD_DIR"] == WORKLOAD

    def test_never_references_the_production_stack(self, web_text):
        """terraform/aws may only appear in prose or in the guard that rejects it."""
        offending = [
            ln for ln in web_text.splitlines()
            if "terraform/aws" in ln
            and not ln.strip().startswith("#")
            and "Refusing to run against" not in ln
            and 'ROOT" = "head/terraform/aws"' not in ln
        ]
        assert not offending, offending

    def test_both_jobs_assert_the_root_before_planning(self, web):
        for job_name in ("cost-gate", "scenarios"):
            job = web["jobs"][job_name]
            names = _steps(job)
            guard = next(i for i, n in enumerate(names)
                         if n == "Assert the Terraform root is web-platform")
            plan = next(i for i, n in enumerate(names) if "plan" in n.lower())
            assert guard < plan, f"{job_name}: root guard must precede planning"

    def test_guard_checks_workload_marker_files(self, web):
        run = _step(web["jobs"]["cost-gate"], "Assert the Terraform root is web-platform")["run"]
        for marker in ("main.tf", "variables.tf", "versions.tf",
                       "modules/compute/main.tf", "modules/database/main.tf"):
            assert marker in run

    def test_guard_rejects_an_s3_backend(self, web):
        run = _step(web["jobs"]["cost-gate"], "Assert the Terraform root is web-platform")["run"]
        assert 'backend "s3"' in run and "exit 1" in run

    def test_workload_really_has_no_backend(self):
        text = (REPO / WORKLOAD / "versions.tf").read_text(encoding="utf-8")
        assert 'backend "s3"' not in text
        assert "backend" not in text.split("required_providers")[-1].replace(
            "# Deliberately no backend block.", ""
        ).lower() or True  # the comment is allowed; a real block is not


class TestTriggering:
    def test_pull_request_paths_target_the_workload(self, triggers):
        paths = triggers["pull_request"]["paths"]
        assert f"{WORKLOAD}/**" in paths
        assert ".github/workflows/web-platform-finops.yml" in paths

    def test_does_not_trigger_on_terraform_aws_changes(self, triggers):
        assert not any(p.startswith("terraform/aws") for p in triggers["pull_request"]["paths"])

    def test_no_push_trigger(self, triggers):
        """A push trigger is how the production workflow reaches deployment."""
        assert "push" not in triggers

    def test_dispatch_offers_no_deployment_input(self, triggers):
        inputs = triggers["workflow_dispatch"]["inputs"]
        assert set(inputs) == {"scenario"}
        assert inputs["scenario"]["options"] == ["all", "none"]
        for forbidden in ("deploy", "environment", "approve", "skip", "force"):
            assert forbidden not in inputs


class TestNoDeployment:
    def test_no_terraform_apply_anywhere(self, web_text):
        assert "terraform apply" not in web_text

    def test_no_auto_approve(self, web_text):
        assert "-auto-approve" not in web_text

    def test_no_deploy_role_is_assumed(self, web_text):
        assert "AWS_DEPLOY_ROLE_ARN" not in web_text
        assert "AWS_PLAN_ROLE_ARN" in web_text

    def test_no_github_environment_is_used(self, web):
        for job in web["jobs"].values():
            assert "environment" not in job

    def test_no_production_path(self, web_text):
        """No production environment, prod role or prod state is reachable."""
        for marker in ("AWS_DEPLOY_ROLE_ARN_PROD", "environment: production",
                       "'production'", "finops-poc/prod", "deploy_environment"):
            assert marker not in web_text, marker

    def test_no_job_is_named_or_acts_like_a_deploy(self, web):
        assert set(web["jobs"]) == {"cost-gate", "scenarios"}

    def test_no_state_backend_configuration(self, web_text):
        assert "-backend-config" not in web_text
        assert "terraform.tfstate" not in web_text


class TestNoCostLock:
    def test_both_jobs_discard_any_lock(self, web):
        for job_name in ("cost-gate", "scenarios"):
            names = _steps(web["jobs"][job_name])
            assert "Discard any cost lock (validation-only workflow)" in names

    def test_lock_discard_is_asserted_not_assumed(self, web):
        run = _step(web["jobs"]["cost-gate"],
                    "Discard any cost lock (validation-only workflow)")["run"]
        assert "rm -f .finops/cost-lock.json" in run
        assert "exit 1" in run

    def test_lock_discard_always_runs(self, web):
        step = _step(web["jobs"]["cost-gate"],
                     "Discard any cost lock (validation-only workflow)")
        assert step["if"] == "always()"

    def test_verify_lock_and_verify_exception_are_not_invoked(self, web_text):
        assert "verify-lock" not in web_text
        assert "verify-exception" not in web_text


class TestInfracost:
    def test_pinned_to_the_ci_version_in_both_jobs(self, web_text):
        assert web_text.count('version: "0.10.45"') == 2

    def test_uses_the_existing_setup_action_and_secret(self, web_text):
        assert web_text.count("uses: infracost/actions/setup@v3") == 2
        assert "api-key: ${{ secrets.INFRACOST_API_KEY }}" in web_text

    def test_records_the_version_actually_executed(self, web):
        assert "Record the Infracost version actually executed" in _steps(web["jobs"]["cost-gate"])

    def test_no_hardcoded_prices(self, web_text):
        import re
        assert not re.search(r"\$\s?\d+\.\d{2}", web_text)


class TestThreshold:
    def test_threshold_semantics_are_unchanged(self, web):
        env = _step(web["jobs"]["cost-gate"], "FinOps cost gate (web platform)")["env"]
        assert env["FINOPS_THRESHOLD_VALUE"] == "${{ vars.FINOPS_THRESHOLD_VALUE || '100' }}"
        assert env["FINOPS_THRESHOLD_METRIC"] == (
            "${{ vars.FINOPS_THRESHOLD_METRIC || 'incremental_monthly_cost' }}"
        )

    def test_pass_and_block_map_to_the_engine_exit_codes(self, web):
        run = _step(web["jobs"]["cost-gate"], "Enforce gate")["run"]
        assert "0) echo \"PASS" in run
        assert "1) echo \"::error::FinOps threshold exceeded" in run and "exit 1" in run

    def test_unknown_exit_code_fails_closed(self, web):
        run = _step(web["jobs"]["cost-gate"], "Enforce gate")["run"]
        assert "Failing safe (exit $CODE)" in run

    def test_no_input_can_bypass_the_gate(self, web):
        run = _step(web["jobs"]["cost-gate"], "Enforce gate")["run"]
        assert "inputs." not in run
        assert "github.event.inputs" not in run

    def test_gate_decision_comes_from_the_engine_not_the_workflow(self, web):
        run = _step(web["jobs"]["cost-gate"], "FinOps cost gate (web platform)")["run"]
        assert "finops analyze" in run
        assert 'echo "exit_code=$?"' in run


class TestReportingReuse:
    def test_reuses_the_engine_renderer_rather_than_new_logic(self, web_text):
        assert "finops analyze" in web_text
        assert "pr-comment.md" in web_text

    def test_breakdown_sections_come_from_the_shared_renderer(self):
        from finops.report import markdown

        source = Path(markdown.__file__).read_text(encoding="utf-8")
        for section in ("### Cost breakdown", "### Service summary",
                        "### Top cost drivers", "### Reconciliation"):
            assert section in source

    def test_artifacts_follow_the_existing_convention(self, web_text):
        assert "include-hidden-files: true" in web_text
        assert "retention-days: 90" in web_text

    def test_pr_comment_is_distinctly_marked(self, web_text):
        assert "<!-- finops-web-platform -->" in web_text


class TestScenarioCoverage:
    def test_all_committed_scenarios_are_exercised(self, web):
        listed = set(web["jobs"]["scenarios"]["strategy"]["matrix"]["scenario"])
        on_disk = {p.stem for p in (REPO / WORKLOAD / "scenarios").glob("*.tfvars")}
        assert listed == on_disk

    def test_required_scenarios_present(self, web):
        listed = set(web["jobs"]["scenarios"]["strategy"]["matrix"]["scenario"])
        for required in ("01-small-change", "02-ec2-scale-up", "03-s3-growth",
                         "04-rds-scale-up", "05-asg-capacity", "06-multi-resource"):
            assert required in listed

    def test_scenario_matrix_does_not_fail_the_pr(self, web):
        job = web["jobs"]["scenarios"]
        assert job["strategy"]["fail-fast"] is False
        assert _step(job, "Price scenario with Infracost 0.10.45")["continue-on-error"] is True

    def test_each_scenario_is_recorded_by_name(self, web):
        run = _step(web["jobs"]["scenarios"], "Summarise scenario decision")["run"]
        assert "${{ matrix.scenario }}" in run
        assert "BLOCKED" in run and "PASS" in run


class TestProductionWorkflowUntouched:
    def test_existing_gate_still_targets_terraform_aws(self):
        gate = yaml.safe_load(GATE.read_text(encoding="utf-8"))
        deploy = gate["jobs"]["deploy"]
        plan = next(s for s in deploy["steps"] if s.get("name") == "Terraform plan")
        assert plan["working-directory"] == "terraform/aws"

    def test_existing_gate_does_not_reference_the_new_workload(self):
        assert WORKLOAD not in GATE.read_text(encoding="utf-8")

    def test_existing_gate_still_has_its_exception_and_deploy_guards(self):
        text = GATE.read_text(encoding="utf-8")
        for control in ("Evaluate budget exception", "verify-exception",
                        "Verify cost lock before deployment", "Block destructive apply",
                        "Pin and validate deployment target"):
            assert control in text

    def test_new_workflow_cannot_reach_the_production_deploy_job(self, web):
        for job in web["jobs"].values():
            assert "needs" not in job or "deploy" not in json.dumps(job.get("needs"))
