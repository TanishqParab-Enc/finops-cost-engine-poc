"""Unit tests for the finops_decision/approval_status/deployment_authorization
tuple `evaluate_approval` returns - the exact values the FinOps Cost Gate
workflow's "Enforce gate" step branches on when deciding whether a BLOCKed,
PENDING (approval-required) run should fail the job or not."""

from __future__ import annotations

import pytest

from finops.gate import evaluate_approval

pytestmark = pytest.mark.unit


def test_block_pending_stays_denied_and_never_becomes_pass():
    """A. Threshold exceeded, no approval yet: BLOCK/PENDING/DENIED - the
    state the workflow's Enforce gate step must now treat as a successful
    step outcome, not a process error."""
    result = evaluate_approval(analyze_exit_code=1)
    assert result["finops_decision"] == "BLOCK"
    assert result["approval_status"] == "PENDING"
    assert result["deployment_authorization"] == "DENIED"


def test_pass_authorizes_when_lock_verified():
    """B. Within threshold: existing PASS/authorization behaviour is
    unchanged by this fix."""
    result = evaluate_approval(analyze_exit_code=0, lock_verified=True)
    assert result["finops_decision"] == "PASS"
    assert result["approval_status"] == "NOT_REQUIRED"
    assert result["deployment_authorization"] == "AUTHORIZED"


def test_pass_denies_when_lock_not_verified():
    """B. Within threshold but a stale/mismatched cost lock still denies -
    unchanged existing behaviour."""
    result = evaluate_approval(analyze_exit_code=0, lock_verified=False)
    assert result["finops_decision"] == "PASS"
    assert result["deployment_authorization"] == "DENIED"


def test_block_approved_authorizes_without_ever_becoming_pass():
    """C. A human approves a BLOCKed change: approval_status and
    deployment_authorization move, but finops_decision never rewrites to
    PASS."""
    result = evaluate_approval(
        analyze_exit_code=1, approval_action="approve", approval_problems=[]
    )
    assert result["finops_decision"] == "BLOCK"
    assert result["approval_status"] == "APPROVED"
    assert result["deployment_authorization"] == "AUTHORIZED"


def test_block_rejected_stays_denied():
    """D. A human rejects a BLOCKed change: deployment_authorization stays
    DENIED (Terraform apply must not run)."""
    result = evaluate_approval(analyze_exit_code=1, approval_action="reject")
    assert result["finops_decision"] == "BLOCK"
    assert result["approval_status"] == "REJECTED"
    assert result["deployment_authorization"] == "DENIED"


def test_untrusted_cost_estimate_is_never_authorized_even_with_approval():
    """E. exit_code 2 (cost could not be trusted) must never be authorized,
    even if an 'approve' action is somehow supplied - this is exactly why the
    workflow's Enforce gate step still fails on any exit code other than 1,
    branching on the raw exit code rather than on this tuple alone."""
    result = evaluate_approval(
        analyze_exit_code=2, approval_action="approve", approval_problems=[]
    )
    assert result["finops_decision"] == "BLOCK"
    assert result["approval_status"] == "PENDING"
    assert result["deployment_authorization"] == "DENIED"
