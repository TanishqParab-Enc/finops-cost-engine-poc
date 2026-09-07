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

from finops.gate import authorize_deployment, finops_decision_label
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
        assert payload == {
            "finops_decision": "PASS",
            "approval_status": "NOT_REQUIRED",
            "deployment_authorization": "AUTHORIZED",
        }

    def test_above_threshold_no_exception_json(self):
        proc = self._run("--exit-code", "1", "--json")
        assert proc.returncode == 1
        payload = json.loads(proc.stdout)
        assert payload == {
            "finops_decision": "BLOCK",
            "approval_status": "PENDING",
            "deployment_authorization": "DENIED",
        }

    def test_above_threshold_valid_exception_json(self):
        proc = self._run("--exit-code", "1", "--exception-valid", "--json")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload == {
            "finops_decision": "BLOCK",
            "approval_status": "APPROVED",
            "deployment_authorization": "AUTHORIZED",
        }

    def test_non_authoritative_exit_code_json(self):
        proc = self._run("--exit-code", "2", "--json")
        assert proc.returncode == 1
        payload = json.loads(proc.stdout)
        assert payload == {
            "finops_decision": "BLOCK",
            "approval_status": "PENDING",
            "deployment_authorization": "DENIED",
        }

