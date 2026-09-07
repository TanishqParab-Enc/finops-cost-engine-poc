"""APPROVE / REJECT of a BLOCKED cost estimate.

The human decision is a workflow_dispatch run whose event and actor GitHub
attests. Three states stay separate throughout: an approval moves
deployment_authorization only, never finops_decision.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal

import pytest
import yaml

from finops.gate import (
    APPROVAL_APPROVED,
    APPROVAL_NOT_REQUIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    REJECTION_MESSAGE,
    evaluate_approval,
)
from finops.lock.exception import create_exception, verify_dispatch_approval
from finops.models import (
    Action,
    Cloud,
    CostEstimate,
    EstimatorTrust,
    NormalizedPlan,
    PolicyDecision,
    ResourceChange,
    Status,
)
from tests.conftest import make_config
from tests.unit.test_stack_matrix import GATE, REPO

APPROVER = "TanishqParab-Enc"
INTRUDER = "mallory"
HEAD = "a" * 40
PR = 15
STACK = "web-platform"
TF_DIR = "terraform/workloads/web-platform"


def _plan(instance_type="t3.large") -> NormalizedPlan:
    return NormalizedPlan(
        terraform_version="1.11.0", format_version="1.2",
        changes=[ResourceChange(
            address="aws_instance.app[0]", resource_type="aws_instance", name="app",
            cloud=Cloud.AWS, action=Action.CREATE, before={},
            after={"instance_type": instance_type})],
        clouds=[Cloud.AWS])


def _plan_doc(region="us-east-1"):
    return {"variables": {"region": {"value": region}, "instance_type": {"value": "t3.large"}}}


def _estimate(inc="259.02", trust=EstimatorTrust.AUTHORITATIVE):
    return CostEstimate(
        currency="USD", estimator="infracost", estimator_version="0.10.45", trust=trust,
        previous_monthly_cost=Decimal("0"), new_monthly_cost=Decimal(inc),
        incremental_monthly_cost=Decimal(inc))


def _decision(observed="259.02"):
    return PolicyDecision(
        status=Status.FAIL, metric="incremental_monthly_cost", unit="USD/month",
        observed_value=Decimal(observed), threshold_value=Decimal("100"),
        currency="USD", comparison="<=")


@pytest.fixture(scope="module")
def gate() -> dict:
    return yaml.safe_load(GATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gate_text() -> str:
    return GATE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
class TestThresholdDecision:
    """The cost decision itself is untouched by any approval concept."""

    def test_below_threshold_is_pass_and_needs_no_approval(self):
        states = evaluate_approval(analyze_exit_code=0)
        assert states["finops_decision"] == "PASS"
        assert states["approval_status"] == APPROVAL_NOT_REQUIRED
        assert states["deployment_authorization"] == "AUTHORIZED"

    def test_above_threshold_is_block_and_requires_approval(self):
        states = evaluate_approval(analyze_exit_code=1)
        assert states["finops_decision"] == "BLOCK"
        assert states["approval_status"] == APPROVAL_PENDING
        assert states["deployment_authorization"] == "DENIED"

    def test_untrustworthy_cost_is_never_authorised(self):
        for action in (None, "approve", "reject"):
            states = evaluate_approval(analyze_exit_code=2, approval_action=action)
            assert states["deployment_authorization"] == "DENIED"


class TestApprovalStateMachine:
    def test_approve_authorises_without_changing_the_decision(self):
        states = evaluate_approval(analyze_exit_code=1, approval_action="approve")
        assert states["finops_decision"] == "BLOCK"
        assert states["approval_status"] == APPROVAL_APPROVED
        assert states["deployment_authorization"] == "AUTHORIZED"

    def test_reject_denies_and_reports_the_exact_message(self):
        states = evaluate_approval(analyze_exit_code=1, approval_action="reject")
        assert states["finops_decision"] == "BLOCK"
        assert states["approval_status"] == APPROVAL_REJECTED
        assert states["deployment_authorization"] == "DENIED"
        assert states["message"] == "Deployment cancelled because the cost estimate was rejected."

    def test_rejection_message_constant_is_exact(self):
        assert REJECTION_MESSAGE == "Deployment cancelled because the cost estimate was rejected."

    def test_block_never_becomes_pass(self):
        for action in (None, "approve", "reject"):
            states = evaluate_approval(analyze_exit_code=1, approval_action=action)
            assert states["finops_decision"] == "BLOCK"

    def test_an_approval_that_fails_its_bindings_is_not_an_approval(self):
        states = evaluate_approval(
            analyze_exit_code=1, approval_action="approve",
            approval_problems=["Incremental cost 280.0 exceeds the approved ceiling 259.02"])
        assert states["approval_status"] == APPROVAL_PENDING
        assert states["deployment_authorization"] == "DENIED"

    def test_pass_with_a_failed_lock_reverification_is_denied(self):
        states = evaluate_approval(analyze_exit_code=0, lock_verified=False)
        assert states["deployment_authorization"] == "DENIED"


class TestApprovalBinding:
    """Every binding is re-checked on trusted main against a FRESH plan and
    estimate, so nothing approved on the PR can drift before it deploys."""

    def _record(self, **overrides):
        kwargs = dict(
            decision=_decision(), estimate=_estimate(), plan=_plan(), plan_doc=_plan_doc(),
            config=make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, head_sha=HEAD, approver=APPROVER,
            justification="approved via workflow_dispatch",
            stack=STACK, terraform_dir=TF_DIR, max_incremental_cost=259.02,
        )
        kwargs.update(overrides)
        return create_exception(
            kwargs.pop("decision"), kwargs.pop("estimate"), kwargs.pop("plan"),
            kwargs.pop("plan_doc"), kwargs.pop("config"), **kwargs)

    def _verify(self, record, **overrides):
        kwargs = dict(
            plan=_plan(), plan_doc=_plan_doc(), estimate=_estimate(),
            config=make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, head_sha=HEAD, stack=STACK, terraform_dir=TF_DIR,
            run_event="workflow_dispatch", run_actor=APPROVER, expected_approver=APPROVER,
        )
        kwargs.update(overrides)
        return verify_dispatch_approval(
            record, kwargs.pop("plan"), kwargs.pop("plan_doc"), kwargs.pop("estimate"),
            kwargs.pop("config"), **kwargs)

    def test_a_valid_approval_authorises(self):
        assert self._verify(self._record()) == []

    def test_record_keeps_the_fail_decision(self):
        assert self._record()["finops_decision"] == Status.FAIL.value

    def test_record_binds_every_required_field(self):
        record = self._record()
        for field in (
            "pr", "head_sha", "stack", "terraform_dir", "plan_fingerprint",
            "resolved_variables_hash", "approved_incremental_cost",
            "max_incremental_cost", "threshold_value", "threshold_metric",
            "approver", "approved_at", "expires_at", "integrity",
        ):
            assert record.get(field) is not None, field

    def test_unauthorised_actor_is_denied(self):
        assert self._verify(self._record(), run_actor=INTRUDER)

    def test_an_approval_from_another_event_is_denied(self):
        assert self._verify(self._record(), run_event="pull_request")
        assert self._verify(self._record(), run_event="push")

    def test_record_approver_must_match_the_attested_actor(self):
        record = self._record(approver=INTRUDER)
        assert self._verify(record)

    def test_wrong_pr_is_denied(self):
        assert self._verify(self._record(), pr_number=PR + 1)

    def test_wrong_head_sha_is_denied(self):
        assert self._verify(self._record(), head_sha="b" * 40)

    def test_wrong_stack_is_denied(self):
        assert self._verify(self._record(), stack="aws")

    def test_wrong_terraform_root_is_denied(self):
        assert self._verify(self._record(), terraform_dir="terraform/aws")

    def test_changed_plan_fingerprint_is_denied(self):
        assert self._verify(self._record(), plan=_plan(instance_type="m5.24xlarge"))

    def test_changed_configuration_is_denied(self):
        changed = {"variables": {"region": {"value": "us-east-1"},
                                 "instance_type": {"value": "m5.4xlarge"}}}
        assert self._verify(self._record(), plan_doc=changed)

    def test_changed_region_is_denied(self):
        assert self._verify(self._record(), plan_doc=_plan_doc(region="eu-west-1"))

    def test_cost_creep_above_the_approved_ceiling_is_denied(self):
        problems = self._verify(self._record(), estimate=_estimate("280.00"))
        assert any("exceeds the approved ceiling" in p for p in problems)

    def test_cost_at_the_ceiling_is_allowed(self):
        assert self._verify(self._record(), estimate=_estimate("259.02")) == []

    def test_expired_approval_is_denied(self):
        from finops.lock.exception import _integrity

        record = self._record()
        record["expires_at"] = "2000-01-01T00:00:00+00:00"
        record["integrity"] = _integrity(record)
        assert any("expired" in p for p in self._verify(record))

    def test_tampered_record_is_denied(self):
        record = self._record()
        record["max_incremental_cost"] = 10_000.0
        assert any("integrity" in p for p in self._verify(record))

    def test_non_authoritative_estimate_is_denied(self):
        problems = self._verify(
            self._record(), estimate=_estimate(trust=EstimatorTrust.NON_AUTHORITATIVE))
        assert any("non-authoritative" in p for p in problems)


class TestApprovalCli:
    """The workflow shells out to these exact commands."""

    def _approve(self, tmp_path, *extra, action="approve", actor=APPROVER,
                 event="workflow_dispatch"):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({
            "terraform_version": "1.11.0", "format_version": "1.2",
            "resource_changes": [{
                "address": "aws_instance.app[0]", "type": "aws_instance", "name": "app",
                "change": {"actions": ["create"], "before": None,
                           "after": {"instance_type": "t3.large"}}}],
            "variables": {"region": {"value": "us-east-1"}},
        }), encoding="utf-8")
        result = tmp_path / "gate-result.json"
        result.write_text(json.dumps({
            "status": "FAIL",
            "cost": {"currency": "USD", "estimator": "infracost",
                     "estimator_version": "0.10.45", "trust": "AUTHORITATIVE",
                     "previous_monthly_cost": "0", "new_monthly_cost": "259.02",
                     "incremental_monthly_cost": "259.02"},
            "policy": {"metric": "incremental_monthly_cost", "unit": "USD/month",
                       "observed_value": "259.02", "threshold_value": "100",
                       "currency": "USD", "comparison": "<="},
        }), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "finops.cli", "approve",
             "--action", action, "--result", str(result), "--plan", str(plan),
             "--pr", str(PR), "--head-sha", HEAD, "--stack", STACK,
             "--terraform-dir", TF_DIR, "--run-event", event, "--run-actor", actor,
             "--expected-approver", APPROVER, "--json", *extra],
            capture_output=True, text=True)

    def test_reject_emits_the_exact_states_and_message(self, tmp_path):
        proc = self._approve(tmp_path, action="reject")
        assert proc.returncode == 1
        payload = json.loads(proc.stdout)
        assert payload["finops_decision"] == "BLOCK"
        assert payload["approval_status"] == "REJECTED"
        assert payload["deployment_authorization"] == "DENIED"
        assert payload["message"] == "Deployment cancelled because the cost estimate was rejected."

    def test_reject_mints_no_record(self, tmp_path):
        out = tmp_path / "approved.json"
        self._approve(tmp_path, "--out", str(out), action="reject")
        assert not out.exists()

    def test_approve_emits_block_approved_authorized(self, tmp_path):
        proc = self._approve(tmp_path)
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["finops_decision"] == "BLOCK"
        assert payload["approval_status"] == "APPROVED"
        assert payload["deployment_authorization"] == "AUTHORIZED"

    def test_unauthorised_actor_cannot_approve(self, tmp_path):
        proc = self._approve(tmp_path, actor=INTRUDER)
        assert proc.returncode != 0
        assert "not the authorised approver" in proc.stderr

    def test_approval_outside_workflow_dispatch_is_refused(self, tmp_path):
        proc = self._approve(tmp_path, event="pull_request")
        assert proc.returncode != 0
        assert "workflow_dispatch" in proc.stderr

    def test_approval_verify_round_trip(self, tmp_path):
        out = tmp_path / "approved.json"
        assert self._approve(tmp_path, "--out", str(out)).returncode == 0

        estimate = tmp_path / "estimate.json"
        estimate.write_text(json.dumps({
            "currency": "USD", "estimator": "infracost", "estimator_version": "0.10.45",
            "trust": "AUTHORITATIVE", "previous_monthly_cost": "0",
            "new_monthly_cost": "259.02", "incremental_monthly_cost": "259.02",
        }), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "finops.cli", "approval-verify",
             "--decision", str(out), "--plan", str(tmp_path / "plan.json"),
             "--estimate", str(estimate), "--pr", str(PR), "--head-sha", HEAD,
             "--stack", STACK, "--terraform-dir", TF_DIR,
             "--run-event", "workflow_dispatch", "--run-actor", APPROVER,
             "--expected-approver", APPROVER, "--json"],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["finops_decision"] == "BLOCK"
        assert payload["approval_status"] == "APPROVED"
        assert payload["deployment_authorization"] == "AUTHORIZED"


class TestApprovalWorkflowWiring:
    def test_approve_and_reject_are_the_dispatch_choices(self, gate):
        triggers = gate.get("on") or gate.get(True)
        options = triggers["workflow_dispatch"]["inputs"]["finops_action"]["options"]
        assert options == ["none", "approve", "reject"]

    def test_approval_defaults_to_doing_nothing(self, gate):
        triggers = gate.get("on") or gate.get(True)
        assert triggers["workflow_dispatch"]["inputs"]["finops_action"]["default"] == "none"

    def test_approval_job_only_runs_on_an_explicit_dispatch(self, gate):
        cond = " ".join(gate["jobs"]["finops-approval"]["if"].split())
        assert "github.event_name == 'workflow_dispatch'" in cond
        assert "inputs.finops_action != 'none'" in cond

    def test_approver_is_repository_config_not_an_input(self, gate):
        assert gate["env"]["FINOPS_APPROVER"] == "${{ vars.FINOPS_APPROVER || 'TanishqParab-Enc' }}"
        triggers = gate.get("on") or gate.get(True)
        assert "approver" not in triggers["workflow_dispatch"]["inputs"]

    def test_actor_is_authorised_before_any_other_step(self, gate):
        steps = [s.get("name", s.get("uses")) for s in gate["jobs"]["finops-approval"]["steps"]]
        assert steps.index("Authorise the approver") < steps.index("Reject the cost estimate")
        assert steps.index("Authorise the approver") < steps.index(
            "Record the approval for each blocked stack")

    def test_rejection_prints_the_exact_message_and_fails(self, gate):
        step = next(s for s in gate["jobs"]["finops-approval"]["steps"]
                    if s.get("name") == "Reject the cost estimate")
        assert "Deployment cancelled because the cost estimate was rejected." in step["run"]
        assert "exit 1" in step["run"]

    def test_head_sha_comes_from_the_api_not_an_input(self, gate):
        triggers = gate.get("on") or gate.get(True)
        assert "head_sha" not in triggers["workflow_dispatch"]["inputs"]
        step = next(s for s in gate["jobs"]["finops-approval"]["steps"]
                    if s.get("name") == "Resolve the pull request being approved")
        assert "pulls/$PR_NUMBER" in step["run"]

    def test_approval_binds_to_the_terraform_root(self, gate):
        step = next(s for s in gate["jobs"]["finops-approval"]["steps"]
                    if s.get("name") == "Record the approval for each blocked stack")
        assert "--terraform-dir" in step["run"]
        assert "--run-actor" in step["run"] and "--expected-approver" in step["run"]

    def test_no_sleep_or_polling_waits_for_the_decision(self, gate_text):
        code = [ln for ln in gate_text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        assert not any("sleep" in ln.lower() for ln in code)
        assert not any("while true" in ln.lower() for ln in code)

    def test_no_environment_required_reviewer_is_used(self, gate_text):
        assert "finops-cost-approval" not in gate_text


class TestTrustedMainVerification:
    def test_trusted_main_relocates_the_approving_run_from_the_api(self, gate):
        step = next(s for s in gate["jobs"]["authorize-deploy"]["steps"]
                    if s.get("name") == "Locate the approving dispatch run")
        assert "event=workflow_dispatch" in step["run"]
        assert "FINOPS_APPROVER" in step["run"]

    def test_trusted_main_reverifies_with_a_fresh_plan_and_estimate(self, gate):
        step = next(s for s in gate["jobs"]["authorize-deploy"]["steps"]
                    if s.get("name") == "Aggregate per-stack authorization")
        assert '"finops", "approval-verify"' in step["run"]
        assert "proposed-plan.json" in step["run"]
        assert "cost-estimate.json" in step["run"]

    def test_a_blocked_stack_without_an_approval_record_is_denied(self, gate):
        step = next(s for s in gate["jobs"]["authorize-deploy"]["steps"]
                    if s.get("name") == "Aggregate per-stack authorization")
        assert 'entry["deployment_authorization"] = "DENIED"' in step["run"]

    def test_deploy_depends_on_the_authorization_result(self, gate):
        assert gate["jobs"]["deploy"]["needs"] == ["detect-changes", "authorize-deploy"]
        cond = " ".join(gate["jobs"]["deploy"]["if"].split())
        assert cond.startswith("needs.authorize-deploy.result == 'success' &&")

    def test_deployment_is_never_reachable_from_a_pull_request(self, gate):
        for job in ("authorize-deploy", "deploy"):
            cond = " ".join(gate["jobs"][job]["if"].split())
            assert "pull_request" not in cond
        assert "refs/heads/main" in " ".join(gate["jobs"]["deploy"]["if"].split())

    def test_approval_job_itself_never_runs_terraform(self, gate):
        job = json.dumps(gate["jobs"]["finops-approval"])
        assert "terraform apply" not in job
        assert "terraform plan" not in job
