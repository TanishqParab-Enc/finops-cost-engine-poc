"""Deployment authorisation: a decision (finops_decision) is separate from
whether trusted `main` may deploy (deployment_authorization). An approved
exception authorises deployment without ever rewriting BLOCK to PASS.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal

import pytest

from finops.gate import authorize_deployment, evaluate_pr_attestation, finops_decision_label
from finops.lock.exception import create_exception, verify_exception
from finops.models import CostEstimate, EstimatorTrust, PolicyDecision, Status
from finops.plan.normalizer import NormalizedPlan
from finops.models import Action, Cloud, ResourceChange
from tests.conftest import make_config

APPROVER, AUTHOR, HEAD, PR = "peer-reviewer", "change-author", "a" * 40, 21


def _plan() -> NormalizedPlan:
    return NormalizedPlan(
        terraform_version="1.11.0", format_version="1.2",
        changes=[ResourceChange(
            address="aws_instance.app[0]", resource_type="aws_instance", name="app",
            cloud=Cloud.AWS, action=Action.CREATE, before={},
            after={"instance_type": "t3.large"})],
        clouds=[Cloud.AWS])


def _plan_doc(region="us-east-1"):
    return {"variables": {"region": {"value": region}, "instance_type": {"value": "t3.large"}}}


def _estimate(inc="150.00", trust=EstimatorTrust.AUTHORITATIVE):
    return CostEstimate(
        currency="USD", estimator="infracost", estimator_version="0.10.45", trust=trust,
        previous_monthly_cost=Decimal("0"), new_monthly_cost=Decimal(inc),
        incremental_monthly_cost=Decimal(inc))


def _decision(status, observed):
    return PolicyDecision(
        status=status, metric="incremental_monthly_cost", unit="USD/month",
        observed_value=Decimal(observed), threshold_value=Decimal("100"),
        currency="USD", comparison="<=")


def _reviews(login=APPROVER, commit=HEAD, state="APPROVED"):
    return [{"state": state, "commit_id": commit, "user": {"login": login}}]


class TestFinopsDecisionLabel:
    """The decision label is derived purely from the analyze exit code and is
    never influenced by exception validity or lock verification."""

    def test_exit_code_0_is_pass(self):
        assert finops_decision_label(0) == "PASS"

    def test_exit_code_1_is_block(self):
        assert finops_decision_label(1) == "BLOCK"

    def test_exit_code_2_is_block(self):
        assert finops_decision_label(2) == "BLOCK"


class TestAuthorizeDeploymentPurefunction:
    def test_below_threshold_is_authorized(self):
        assert authorize_deployment(analyze_exit_code=0) == "AUTHORIZED"

    def test_below_threshold_with_failed_lock_reverification_is_denied(self):
        assert authorize_deployment(analyze_exit_code=0, lock_verified=False) == "DENIED"

    def test_above_threshold_with_no_exception_is_denied(self):
        assert authorize_deployment(analyze_exit_code=1, exception_valid=None) == "DENIED"
        assert authorize_deployment(analyze_exit_code=1, exception_valid=False) == "DENIED"

    def test_above_threshold_with_valid_exception_is_authorized(self):
        assert authorize_deployment(analyze_exit_code=1, exception_valid=True) == "AUTHORIZED"

    def test_non_authoritative_or_undecidable_cost_is_denied(self):
        """exit_code 2 means the gate could not trust the cost data (e.g. a
        mocked/non-authoritative estimator) - always fail closed, exception
        or not."""
        assert authorize_deployment(analyze_exit_code=2) == "DENIED"
        assert authorize_deployment(analyze_exit_code=2, exception_valid=True) == "DENIED"

    def test_authorized_via_exception_never_changes_the_decision_label(self):
        assert finops_decision_label(1) == "BLOCK"
        assert authorize_deployment(analyze_exit_code=1, exception_valid=True) == "AUTHORIZED"


class TestAuthorizeDeploymentEndToEndWithRealExceptionValidation:
    """Composes the real verify_exception engine (not a stub) with
    authorize_deployment, proving the full chain for every rejection reason
    the workflow relies on."""

    def _record(self, **overrides):
        kwargs = dict(
            decision=_decision(Status.FAIL, "150.00"), estimate=_estimate("150.00"),
            plan=_plan(), plan_doc=_plan_doc(),
            config=make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, head_sha=HEAD, approver=APPROVER,
            justification="capacity increase", stack="web-platform",
            max_incremental_cost=160.0,
        )
        kwargs.update(overrides)
        return create_exception(
            kwargs.pop("decision"), kwargs.pop("estimate"), kwargs.pop("plan"),
            kwargs.pop("plan_doc"), kwargs.pop("config"), **kwargs)

    def _verify(self, record, **overrides):
        kwargs = dict(
            plan=_plan(), plan_doc=_plan_doc(), estimate=_estimate("150.00"),
            config=make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, pr_author=AUTHOR, head_sha=HEAD, stack="web-platform",
            reviews=_reviews(),
        )
        kwargs.update(overrides)
        return verify_exception(
            record, kwargs.pop("plan"), kwargs.pop("plan_doc"), kwargs.pop("estimate"),
            kwargs.pop("config"), **kwargs)

    def test_valid_peer_approval_authorizes_deployment(self):
        record = self._record()
        problems = self._verify(record)
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems == []
        assert auth == "AUTHORIZED"

    def test_wrong_reviewer_denies_deployment(self):
        record = self._record()
        problems = self._verify(record, reviews=_reviews(login="someone-not-allowlisted"))
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems
        assert auth == "DENIED"

    def test_author_self_approval_denies_deployment(self):
        record = self._record(approver=AUTHOR)
        problems = self._verify(record, reviews=_reviews(login=AUTHOR))
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems
        assert auth == "DENIED"

    def test_stale_head_sha_denies_deployment(self):
        record = self._record()
        problems = self._verify(record, reviews=_reviews(commit="b" * 40))
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems
        assert auth == "DENIED"

    def test_expired_exception_denies_deployment(self):
        record = self._record()
        record["expires_at"] = "2000-01-01T00:00:00+00:00"
        # Re-sign integrity so expiry is the only broken field being tested.
        from finops.lock.exception import _integrity

        record["integrity"] = _integrity(record)
        problems = self._verify(record)
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems
        assert auth == "DENIED"

    def test_cost_creep_above_ceiling_denies_deployment(self):
        record = self._record()
        problems = self._verify(record, estimate=_estimate("500.00"))
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems
        assert auth == "DENIED"

    def test_non_authoritative_estimate_denies_deployment_even_with_a_valid_exception(self):
        """A mocked/non-authoritative estimate must never authorise deployment,
        even if the exception would otherwise be valid."""
        record = self._record()
        problems = self._verify(
            record, estimate=_estimate("150.00", trust=EstimatorTrust.NON_AUTHORITATIVE))
        auth = authorize_deployment(analyze_exit_code=1, exception_valid=not problems)
        assert problems
        assert auth == "DENIED"


class TestDeployNeverOccursFromPullRequestEvents:
    def test_analyze_never_deploys_anything_itself(self):
        """`analyze` only ever writes gate artifacts - it has no code path
        that invokes terraform apply."""
        import finops.gate as gate_module
        source = gate_module.__file__
        with open(source, encoding="utf-8") as fh:
            body = fh.read()
        assert "terraform apply" not in body
        assert "subprocess" not in body


class TestAuthorizeDeploymentCli:
    """The workflow calls this CLI command rather than re-deriving the same
    logic in bash, so the exact tested function runs in CI."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "finops.cli", "authorize-deployment", *args],
            capture_output=True, text=True,
        )

    def test_below_threshold_json(self):
        proc = self._run("--exit-code", "0", "--json")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload == {"finops_decision": "PASS", "deployment_authorization": "AUTHORIZED"}

    def test_above_threshold_no_exception_json(self):
        proc = self._run("--exit-code", "1", "--json")
        assert proc.returncode == 1
        payload = json.loads(proc.stdout)
        assert payload == {"finops_decision": "BLOCK", "deployment_authorization": "DENIED"}

    def test_above_threshold_valid_exception_json(self):
        proc = self._run("--exit-code", "1", "--exception-valid", "--json")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload == {"finops_decision": "BLOCK", "deployment_authorization": "AUTHORIZED"}

    def test_non_authoritative_exit_code_json(self):
        proc = self._run("--exit-code", "2", "--json")
        assert proc.returncode == 1
        payload = json.loads(proc.stdout)
        assert payload == {"finops_decision": "BLOCK", "deployment_authorization": "DENIED"}


class TestEvaluatePrAttestation:
    """The finops-cost-approval GitHub Actions environment - not a PR review,
    not a workflow input, not repository content - is the only thing that
    can authorise a BLOCKed stack, and only when independently re-verified
    on trusted main using fresh cost data and a live re-check that the PR's
    approval job itself succeeded."""

    def _attestation(self, **overrides):
        kwargs = dict(
            decision=_decision(Status.FAIL, "150.00"), estimate=_estimate("150.00"),
            plan=_plan(), plan_doc=_plan_doc(),
            config=make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, head_sha=HEAD, approver=APPROVER,
            justification="Approved via the finops-cost-approval GitHub Actions environment",
            stack="web-platform", max_incremental_cost=160.0,
        )
        kwargs.update(overrides)
        return create_exception(
            kwargs.pop("decision"), kwargs.pop("estimate"), kwargs.pop("plan"),
            kwargs.pop("plan_doc"), kwargs.pop("config"), **kwargs)

    def _evaluate(self, attestation, **overrides):
        kwargs = dict(
            plan=_plan(), plan_doc=_plan_doc(), estimate=_estimate("150.00"),
            config=make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, pr_author=AUTHOR, head_sha=HEAD, stack="web-platform",
            approval_job_succeeded=True, approver_logins=[APPROVER],
        )
        kwargs.update(overrides)
        return evaluate_pr_attestation(attestation, **kwargs)

    def test_valid_environment_approval_authorizes(self):
        attestation = self._attestation()
        assert self._evaluate(attestation) == "AUTHORIZED"

    def test_approval_never_changes_finops_decision(self):
        attestation = self._attestation()
        assert attestation["finops_decision"] == Status.FAIL.value
        assert self._evaluate(attestation) == "AUTHORIZED"
        assert attestation["finops_decision"] == Status.FAIL.value

    def test_approval_job_not_succeeded_denies_even_with_a_perfect_attestation(self):
        """A GitHub Actions environment approval is scoped to the run it was
        granted on - it must never be assumed to carry over to trusted main."""
        attestation = self._attestation()
        assert self._evaluate(attestation, approval_job_succeeded=False) == "DENIED"

    def test_no_attestation_at_all_denies(self):
        assert self._evaluate(None) == "DENIED"

    def test_no_approver_logins_denies(self):
        """Nothing recorded by the live Approvals API on the source run -
        fail closed rather than assume approval."""
        attestation = self._attestation()
        assert self._evaluate(attestation, approver_logins=[]) == "DENIED"

    def test_wrong_reviewer_login_denies(self):
        attestation = self._attestation()
        assert self._evaluate(attestation, approver_logins=["someone-not-allowlisted"]) == "DENIED"

    def test_author_self_approval_denies(self):
        attestation = self._attestation(approver=AUTHOR)
        assert self._evaluate(attestation, approver_logins=[AUTHOR]) == "DENIED"

    def test_wrong_head_sha_denies(self):
        """A new commit pushed to the PR after approval must invalidate it."""
        attestation = self._attestation()
        assert self._evaluate(attestation, head_sha="b" * 40) == "DENIED"

    def test_wrong_pr_denies(self):
        attestation = self._attestation()
        assert self._evaluate(attestation, pr_number=PR + 1) == "DENIED"

    def test_wrong_stack_denies(self):
        attestation = self._attestation()
        assert self._evaluate(attestation, stack="aws") == "DENIED"

    def test_expired_attestation_denies(self):
        attestation = self._attestation()
        attestation["expires_at"] = "2000-01-01T00:00:00+00:00"
        from finops.lock.exception import _integrity

        attestation["integrity"] = _integrity(attestation)
        assert self._evaluate(attestation) == "DENIED"

    def test_cost_creep_above_ceiling_denies(self):
        """Fresh cost on trusted main, not the PR's cached number, decides this."""
        attestation = self._attestation()
        assert self._evaluate(attestation, estimate=_estimate("500.00")) == "DENIED"

    def test_non_authoritative_fresh_estimate_denies(self):
        attestation = self._attestation()
        assert self._evaluate(
            attestation, estimate=_estimate("150.00", trust=EstimatorTrust.NON_AUTHORITATIVE),
        ) == "DENIED"

    def test_tampered_attestation_denies(self):
        attestation = self._attestation()
        attestation["approved_incremental_cost"] = 1.0  # tampered, not re-signed
        assert self._evaluate(attestation) == "DENIED"

    def test_missing_plan_or_estimate_denies(self):
        """Nothing fresh to compare the attestation against - fail closed."""
        attestation = self._attestation()
        assert self._evaluate(attestation, plan=None, plan_doc=None) == "DENIED"
        assert self._evaluate(attestation, estimate=None) == "DENIED"


class TestEvaluateAttestationCli:
    """Smoke-tests the CLI wiring authorize-deploy actually calls - the
    engine-level TestEvaluatePrAttestation above covers every rejection
    reason directly."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "finops.cli", "evaluate-attestation", *args],
            capture_output=True, text=True,
        )

    def test_no_exception_file_denies(self, tmp_path):
        proc = self._run(
            "--exception", str(tmp_path / "missing.json"),
            "--approval-job-conclusion", "success", "--approver-logins", APPROVER,
            "--pr", str(PR), "--head-sha", HEAD, "--stack", "web-platform", "--json",
        )
        assert proc.returncode == 1
        assert json.loads(proc.stdout) == {"deployment_authorization": "DENIED"}

    def test_approval_job_not_success_denies_without_reading_the_exception(self, tmp_path):
        exc_path = tmp_path / "attestation.json"
        exc_path.write_text("{}", encoding="utf-8")
        proc = self._run(
            "--exception", str(exc_path),
            "--approval-job-conclusion", "failure", "--approver-logins", APPROVER,
            "--pr", str(PR), "--head-sha", HEAD, "--stack", "web-platform", "--json",
        )
        assert proc.returncode == 1
        assert json.loads(proc.stdout) == {"deployment_authorization": "DENIED"}

    def test_full_chain_via_create_exception_cli_authorizes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINOPS_APPROVERS", APPROVER)

        plan_doc = {
            "terraform_version": "1.11.0", "format_version": "1.2",
            "resource_changes": [{
                "address": "aws_instance.app[0]", "type": "aws_instance", "name": "app",
                "change": {"actions": ["create"], "before": None, "after": {"instance_type": "t3.large"}},
            }],
            "variables": {"region": {"value": "us-east-1"}},
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_doc), encoding="utf-8")

        gate_result = {
            "status": "FAIL",
            "cost": {
                "currency": "USD", "estimator": "infracost", "estimator_version": "0.10.45",
                "trust": "AUTHORITATIVE", "previous_monthly_cost": "0",
                "new_monthly_cost": "150.00", "incremental_monthly_cost": "150.00",
            },
            "policy": {
                "metric": "incremental_monthly_cost", "unit": "USD/month",
                "observed_value": "150.00", "threshold_value": "100", "currency": "USD",
                "comparison": "<=",
            },
        }
        gate_result_path = tmp_path / "gate-result.json"
        gate_result_path.write_text(json.dumps(gate_result), encoding="utf-8")

        attestation_path = tmp_path / "attestation.json"
        create = subprocess.run(
            [sys.executable, "-m", "finops.cli", "create-exception",
             "--result", str(gate_result_path), "--plan", str(plan_path),
             "--pr", str(PR), "--head-sha", HEAD, "--approver", APPROVER,
             "--justification", "Approved via finops-cost-approval", "--stack", "web-platform",
             "--out", str(attestation_path)],
            capture_output=True, text=True,
        )
        assert create.returncode == 0, create.stderr

        proc = self._run(
            "--exception", str(attestation_path), "--plan", str(plan_path),
            "--gate-result", str(gate_result_path),
            "--pr", str(PR), "--pr-author", AUTHOR, "--head-sha", HEAD, "--stack", "web-platform",
            "--approval-job-conclusion", "success", "--approver-logins", APPROVER, "--json",
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert json.loads(proc.stdout) == {"deployment_authorization": "AUTHORIZED"}

