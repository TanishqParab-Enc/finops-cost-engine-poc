"""Budget exception: binding, staleness and authorisation.

The exception is the only sanctioned way an over-threshold change proceeds, so
every one of these paths must fail closed.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finops.config import ExceptionConfig
from finops.lock.exception import (
    BudgetExceptionError,
    _integrity,
    create_exception,
    resolved_variables_hash,
    verify_exception,
)
from finops.models import (
    Cloud,
    CostEstimate,
    EstimatorTrust,
    NormalizedPlan,
    PolicyDecision,
    ResourceChange,
    Action,
    Status,
)
from tests.conftest import make_config

APPROVER = "peer-reviewer"
AUTHOR = "change-author"
HEAD_SHA = "b4d5aeb4acfbf9517610d5eb3d2a12adc596106f"
PR = 7


def _plan(instance_type: str = "m5.4xlarge") -> NormalizedPlan:
    return NormalizedPlan(
        terraform_version="1.11.0",
        format_version="1.2",
        changes=[
            ResourceChange(
                address="aws_instance.app[0]",
                resource_type="aws_instance",
                name="app",
                cloud=Cloud.AWS,
                action=Action.CREATE,
                before={},
                after={"instance_type": instance_type},
            )
        ],
        clouds=[Cloud.AWS],
    )


def _plan_doc(region: str = "us-east-1", instance_type: str = "m5.4xlarge") -> dict:
    return {
        "variables": {
            "region": {"value": region},
            "instance_type": {"value": instance_type},
            "instance_count": {"value": 1},
            "root_volume_size_gb": {"value": 20},
            "data_volume_count": {"value": 0},
            "data_volume_size_gb": {"value": 100},
            "enable_nat_gateway": {"value": False},
            "environment": {"value": "Dev"},
            "service": {"value": "finops-poc"},
            "ami_id": {"value": "ami-0c02fb55956c7d316"},
        }
    }


def _estimate(incremental: str = "553.05") -> CostEstimate:
    return CostEstimate(
        currency="USD",
        estimator="infracost (v0.10 schema)",
        estimator_version="0.10.45",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal("9.19"),
        new_monthly_cost=Decimal("9.19") + Decimal(incremental),
        incremental_monthly_cost=Decimal(incremental),
    )


def _decision(observed: str = "553.05", threshold: str = "100") -> PolicyDecision:
    return PolicyDecision(
        status=Status.FAIL,
        metric="incremental_monthly_cost",
        unit="USD/month",
        observed_value=Decimal(observed),
        threshold_value=Decimal(threshold),
        currency="USD",
        comparison="<=",
    )


def _config(**kwargs):
    kwargs.setdefault("approvers", [APPROVER])
    return make_config(**kwargs)


def _reviews(
    login: str = APPROVER, state: str = "APPROVED", commit_id: str = HEAD_SHA
) -> list[dict]:
    return [{"state": state, "commit_id": commit_id, "user": {"login": login}}]


def _record(config=None, **overrides):
    config = config or _config()
    record = create_exception(
        _decision(),
        _estimate(),
        _plan(),
        _plan_doc(),
        config,
        pr_number=PR,
        head_sha=HEAD_SHA,
        approver=APPROVER,
        justification="Load-test capacity for the Q4 launch.",
        max_incremental_cost=overrides.pop("max_incremental_cost", 570.00),
    )
    record.update(overrides)
    if overrides:
        _resign(record)
    return record


def _resign(record: dict) -> dict:
    """Re-seal a deliberately mutated record so tests isolate one failure each."""
    record["integrity"] = _integrity(record)
    return record


def _verify(record, config=None, **kwargs):
    config = config or _config()
    kwargs.setdefault("plan", _plan())
    kwargs.setdefault("plan_doc", _plan_doc())
    kwargs.setdefault("estimate", _estimate())
    kwargs.setdefault("pr_number", PR)
    kwargs.setdefault("pr_author", AUTHOR)
    kwargs.setdefault("head_sha", HEAD_SHA)
    kwargs.setdefault("reviews", _reviews())
    plan = kwargs.pop("plan")
    plan_doc = kwargs.pop("plan_doc")
    estimate = kwargs.pop("estimate")
    return verify_exception(record, plan, plan_doc, estimate, config, **kwargs)


class TestCreation:
    def test_refuses_to_approve_a_passing_decision(self):
        passing = PolicyDecision(
            status=Status.PASS,
            metric="incremental_monthly_cost",
            unit="USD/month",
            observed_value=Decimal("1"),
            threshold_value=Decimal("100"),
            currency="USD",
            comparison="<=",
        )
        with pytest.raises(BudgetExceptionError):
            create_exception(
                passing, _estimate(), _plan(), _plan_doc(), _config(),
                pr_number=PR, head_sha=HEAD_SHA, approver=APPROVER, justification="x",
            )

    def test_preserves_the_fail_decision(self):
        assert _record()["finops_decision"] == "FAIL"
        assert _record()["status"] == "APPROVED"

    def test_requires_a_justification(self):
        with pytest.raises(BudgetExceptionError):
            create_exception(
                _decision(), _estimate(), _plan(), _plan_doc(), _config(),
                pr_number=PR, head_sha=HEAD_SHA, approver=APPROVER, justification="   ",
            )

    def test_ceiling_cannot_undercut_the_approved_cost(self):
        with pytest.raises(BudgetExceptionError):
            create_exception(
                _decision(), _estimate(), _plan(), _plan_doc(), _config(),
                pr_number=PR, head_sha=HEAD_SHA, approver=APPROVER,
                justification="x", max_incremental_cost=10.0,
            )

    def test_ceiling_headroom_is_capped(self):
        with pytest.raises(BudgetExceptionError):
            create_exception(
                _decision(), _estimate(), _plan(), _plan_doc(), _config(),
                pr_number=PR, head_sha=HEAD_SHA, approver=APPROVER,
                justification="x", max_incremental_cost=5000.0,
            )

    def test_binds_both_fingerprint_and_resolved_variables(self):
        record = _record()
        assert record["plan_fingerprint"] == _plan().fingerprint()
        assert record["resolved_variables_hash"] == resolved_variables_hash(_plan_doc())


class TestAcceptance:
    def test_1_valid_exception_with_non_author_approval_is_accepted(self):
        assert _verify(_record()) == []


class TestAuthorisation:
    def test_3_no_peer_approval_is_blocked(self):
        problems = _verify(_record(), reviews=[])
        assert any("No APPROVED pull request review" in p for p in problems)

    def test_3b_missing_review_data_is_blocked(self):
        problems = _verify(_record(), reviews=None)
        assert any("cannot authorise" in p for p in problems)

    def test_4_self_approval_is_rejected(self):
        record = _resign({**_record(), "approver": AUTHOR})
        problems = _verify(record, reviews=_reviews(login=AUTHOR))
        assert len(problems) == 1
        assert "self-approval" in problems[0]

    def test_approver_outside_the_allowlist_is_rejected(self):
        problems = _verify(_record(), reviews=_reviews(login="random-person"))
        assert len(problems) == 1
        assert "not in the approver allowlist" in problems[0]

    def test_empty_allowlist_rejects_everything(self):
        config = make_config(approvers=[])
        problems = _verify(_record(config=_config()), config=config)
        assert any("No approver allowlist" in p for p in problems)

    def test_review_on_a_different_commit_is_stale(self):
        problems = _verify(_record(), reviews=_reviews(commit_id="0" * 40))
        assert len(problems) == 1
        assert "stale review" in problems[0]

    def test_changes_requested_is_not_an_approval(self):
        problems = _verify(_record(), reviews=_reviews(state="CHANGES_REQUESTED"))
        assert len(problems) == 1
        assert "No APPROVED pull request review" in problems[0]

    def test_recorded_approver_must_match_the_reviewer(self):
        record = _resign({**_record(), "approver": "someone-else"})
        problems = _verify(record)
        assert len(problems) == 1
        assert "names 'someone-else' as approver" in problems[0]


class TestChangeBinding:
    def test_5_wrong_pr_is_rejected(self):
        problems = _verify(_record(), pr_number=999)
        assert any("approved for PR #7" in p for p in problems)

    def test_6_wrong_head_sha_is_rejected(self):
        problems = _verify(_record(), head_sha="f" * 40)
        assert any("bound to head" in p for p in problems)

    def test_7_terraform_change_after_approval_is_rejected(self):
        problems = _verify(_record(), plan=_plan(instance_type="m5.8xlarge"))
        assert any("Terraform change has been modified" in p for p in problems)

    def test_8_resolved_variable_change_is_rejected(self):
        problems = _verify(_record(), plan_doc=_plan_doc(instance_type="m5.8xlarge"))
        assert any("Resolved Terraform configuration has changed" in p for p in problems)

    def test_9_region_only_change_is_rejected(self):
        """The resource fingerprint is region-blind, so this is the case that
        proves the resolved-variable hash is doing real work."""
        record = _record()
        moved = _plan_doc(region="eu-west-1")
        # The fingerprint still matches - only the variable hash catches this.
        assert record["plan_fingerprint"] == _plan().fingerprint()
        assert record["resolved_variables_hash"] != resolved_variables_hash(moved)
        problems = _verify(record, plan_doc=moved)
        assert len(problems) == 1
        assert "Resolved Terraform configuration has changed" in problems[0]

    def test_plan_without_variables_fails_closed(self):
        problems = _verify(_record(), plan_doc={})
        assert any("no resolved variables" in p for p in problems)


class TestCostBinding:
    def test_10_cost_above_ceiling_is_rejected(self):
        problems = _verify(_record(), estimate=_estimate("600.00"))
        assert any("exceeds the approved ceiling" in p for p in problems)

    def test_cost_at_the_ceiling_is_accepted(self):
        assert _verify(_record(), estimate=_estimate("570.00")) == []

    def test_cost_below_approved_is_accepted(self):
        assert _verify(_record(), estimate=_estimate("120.00")) == []

    def test_currency_change_is_rejected(self):
        estimate = _estimate()
        estimate.currency = "EUR"
        problems = _verify(_record(), estimate=estimate)
        assert any("Currency has changed" in p for p in problems)


class TestPolicyBinding:
    def test_11_threshold_change_is_rejected(self):
        problems = _verify(_record(), config=_config(threshold=50))
        assert any("Threshold has changed" in p for p in problems)

    def test_threshold_metric_change_is_rejected(self):
        problems = _verify(_record(), config=_config(metric="incremental_annual_cost"))
        assert any("Threshold metric has changed" in p for p in problems)

    def test_disabled_exceptions_reject_everything(self):
        problems = _verify(_record(), config=_config(exceptions_enabled=False))
        assert problems == ["Budget exceptions are disabled by policy"]


class TestFreshness:
    def test_12_expired_exception_is_rejected(self):
        record = _resign({**_record(), "expires_at": "2020-01-01T00:00:00Z"})
        problems = _verify(record)
        assert len(problems) == 1
        assert "expired" in problems[0]

    def test_overlong_lifetime_is_rejected(self):
        now = datetime.now(timezone.utc)
        record = _resign(
            {
                **_record(),
                "approved_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "expires_at": (now + timedelta(days=365))
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }
        )
        problems = _verify(record)
        assert len(problems) == 1
        assert "lifetime exceeds" in problems[0]

    def test_unparseable_timestamp_fails_closed(self):
        record = _resign({**_record(), "expires_at": "whenever"})
        problems = _verify(record)
        assert len(problems) == 1
        assert "expires_at" in problems[0]


class TestIntegrity:
    def test_13_tampered_field_is_detected(self):
        record = _record()
        record["max_incremental_cost"] = 99999.0
        problems = _verify(record)
        assert any("integrity hash does not match" in p for p in problems)

    def test_missing_integrity_is_rejected(self):
        record = _record()
        del record["integrity"]
        problems = _verify(record)
        assert any("no integrity hash" in p for p in problems)

    def test_status_must_be_approved(self):
        record = _resign({**_record(), "status": "PENDING"})
        problems = _verify(record)
        assert len(problems) == 1
        assert "status is 'PENDING'" in problems[0]

    def test_downgrading_finops_decision_to_pass_is_rejected(self):
        record = _resign({**_record(), "finops_decision": "PASS"})
        problems = _verify(record)
        assert len(problems) == 1
        assert "does not preserve the original FinOps decision" in problems[0]

    def test_schema_version_mismatch_is_rejected(self):
        record = _resign({**_record(), "schema_version": "9.9"})
        problems = _verify(record)
        assert len(problems) == 1
        assert "schema_version" in problems[0]


class TestIsolationFromTheNormalPath:
    def test_14_below_threshold_path_never_consults_exceptions(self):
        """A PASS produces a cost lock and no exception is involved at all."""
        from finops.lock.cost_lock import create_cost_lock

        config = _config()
        passing = PolicyDecision(
            status=Status.PASS,
            metric="incremental_monthly_cost",
            unit="USD/month",
            observed_value=Decimal("64.89"),
            threshold_value=Decimal("100"),
            currency="USD",
            comparison="<=",
        )
        lock = create_cost_lock(
            passing, _estimate("64.89"), _plan(), config, "abc123", "run-1"
        )
        assert lock["status"] == "APPROVED"
        assert "exception_id" not in lock
        assert "finops_decision" not in lock

    def test_exception_config_defaults_are_fail_closed(self):
        defaults = ExceptionConfig()
        assert defaults.approvers == []
        assert defaults.require_non_author_approval is True
        assert defaults.require_review_approval is True

    def test_verification_is_pure_and_does_not_mutate_the_record(self):
        record = _record()
        before = copy.deepcopy(record)
        _verify(record)
        assert record == before
