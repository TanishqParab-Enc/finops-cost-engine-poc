"""Unit tests for cost lock creation and verification."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.lock.cost_lock import (
    CostLockError,
    create_cost_lock,
    load_cost_lock,
    verify_cost_lock,
    write_cost_lock,
)
from finops.models import (
    Action,
    Cloud,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    NormalizedPlan,
    PolicyDecision,
    ResourceChange,
    Status,
)

from ..conftest import make_config

pytestmark = pytest.mark.unit


def make_plan(instance_type: str = "m5.large") -> NormalizedPlan:
    return NormalizedPlan(
        terraform_version="1.11.0",
        format_version="1.2",
        clouds=[Cloud.AWS],
        changes=[
            ResourceChange(
                address="aws_instance.app",
                resource_type="aws_instance",
                name="app",
                cloud=Cloud.AWS,
                action=Action.CREATE,
                after={"instance_type": instance_type},
            )
        ],
    )


def make_estimate(trust: EstimatorTrust = EstimatorTrust.AUTHORITATIVE) -> CostEstimate:
    return CostEstimate(
        currency="USD",
        estimator="infracost (v2 schema)",
        estimator_version="2.16.2",
        trust=trust,
        previous_monthly_cost=Decimal("9.19"),
        new_monthly_cost=Decimal("74.08"),
        incremental_monthly_cost=Decimal("64.89"),
        coverage=CostCoverage(detected_resources=1, supported_resources=1),
    )


def make_decision(status: Status = Status.PASS) -> PolicyDecision:
    return PolicyDecision(
        status=status,
        metric="incremental_monthly_cost",
        observed_value=Decimal("64.89"),
        threshold_value=Decimal("100"),
        currency="USD",
        comparison="<=",
        unit="USD/month",
    )


class TestCreate:
    def test_contains_required_audit_fields(self):
        lock = create_cost_lock(
            make_decision(), make_estimate(), make_plan(), make_config(), "abc123", "run-1"
        )
        for field in (
            "lock_id",
            "commit",
            "execution_id",
            "timestamp",
            "estimated_incremental_monthly_cost",
            "threshold",
            "currency",
            "status",
            "plan_fingerprint",
            "integrity",
        ):
            assert field in lock, f"missing {field}"
        assert lock["status"] == "APPROVED"
        assert lock["commit"] == "abc123"
        assert lock["estimated_incremental_monthly_cost"] == 64.89

    def test_refuses_on_fail_decision(self):
        with pytest.raises(CostLockError, match="non-PASS"):
            create_cost_lock(
                make_decision(Status.FAIL), make_estimate(), make_plan(), make_config(), "c", "e"
            )

    def test_refuses_on_error_decision(self):
        with pytest.raises(CostLockError, match="non-PASS"):
            create_cost_lock(
                make_decision(Status.ERROR), make_estimate(), make_plan(), make_config(), "c", "e"
            )

    def test_refuses_non_authoritative_estimate(self):
        with pytest.raises(CostLockError, match="non-authoritative"):
            create_cost_lock(
                make_decision(),
                make_estimate(EstimatorTrust.NON_AUTHORITATIVE),
                make_plan(),
                make_config(),
                "c",
                "e",
            )

    def test_allows_non_authoritative_when_explicitly_configured(self):
        lock = create_cost_lock(
            make_decision(),
            make_estimate(EstimatorTrust.NON_AUTHORITATIVE),
            make_plan(),
            make_config(allow_non_authoritative_lock=True),
            "c",
            "e",
        )
        assert lock["estimator_trust"] == "NON_AUTHORITATIVE"

    def test_lock_ids_are_unique(self):
        args = (make_decision(), make_estimate(), make_plan(), make_config(), "c", "e")
        assert create_cost_lock(*args)["lock_id"] != create_cost_lock(*args)["lock_id"]


class TestVerify:
    def test_valid_lock_has_no_problems(self):
        plan = make_plan()
        config = make_config()
        lock = create_cost_lock(make_decision(), make_estimate(), plan, config, "c", "e")
        assert verify_cost_lock(lock, plan, config) == []

    def test_rejects_lock_when_plan_changed(self):
        config = make_config()
        lock = create_cost_lock(make_decision(), make_estimate(), make_plan("m5.large"), config, "c", "e")
        problems = verify_cost_lock(lock, make_plan("m5.24xlarge"), config)
        assert any("modified since approval" in p for p in problems)

    def test_rejects_tampered_lock(self):
        plan = make_plan()
        config = make_config()
        lock = create_cost_lock(make_decision(), make_estimate(), plan, config, "c", "e")
        lock["estimated_incremental_monthly_cost"] = 1.0
        problems = verify_cost_lock(lock, plan, config)
        assert any("integrity" in p for p in problems)

    def test_rejects_when_threshold_changed(self):
        plan = make_plan()
        lock = create_cost_lock(make_decision(), make_estimate(), plan, make_config(threshold=100), "c", "e")
        problems = verify_cost_lock(lock, plan, make_config(threshold=50))
        assert any("Threshold has changed" in p for p in problems)

    def test_rejects_when_metric_changed(self):
        plan = make_plan()
        lock = create_cost_lock(make_decision(), make_estimate(), plan, make_config(), "c", "e")
        problems = verify_cost_lock(lock, plan, make_config(metric="incremental_annual_cost"))
        assert any("metric has changed" in p for p in problems)

    def test_fingerprint_binding_can_be_disabled(self):
        config = make_config()
        lock = create_cost_lock(make_decision(), make_estimate(), make_plan("m5.large"), config, "c", "e")
        relaxed = make_config()
        object.__setattr__(relaxed.cost_lock, "bind_to_plan_fingerprint", False)
        problems = verify_cost_lock(lock, make_plan("m5.24xlarge"), relaxed)
        assert not any("modified since approval" in p for p in problems)


class TestRoundTrip:
    def test_write_then_load(self, tmp_path):
        config = make_config(output_dir=str(tmp_path / "out"))
        plan = make_plan()
        lock = create_cost_lock(make_decision(), make_estimate(), plan, config, "c", "e")
        path = write_cost_lock(lock, config)
        assert path.is_file()
        assert load_cost_lock(path) == lock
        assert verify_cost_lock(load_cost_lock(path), plan, config) == []

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(CostLockError, match="not found"):
            load_cost_lock(tmp_path / "nope.json")
