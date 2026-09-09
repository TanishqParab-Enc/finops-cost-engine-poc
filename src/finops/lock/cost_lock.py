"""Component G - the cost lock.

When a change passes the threshold, the approved estimate is frozen as an
auditable artifact for that CI/CD execution. The lock is bound to a fingerprint
of the normalised plan, so editing the Terraform change invalidates it and a new
estimate must be produced.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..config import Config
from ..errors import PolicyError
from ..models import (
    CostEstimate,
    NormalizedPlan,
    PolicyDecision,
    Status,
    as_float,
    canonical_hash,
    utc_now_iso,
)

SCHEMA_VERSION = "1.0"
LOCK_FILENAME = "cost-lock.json"


class CostLockError(PolicyError):
    pass


def _integrity(body: dict) -> str:
    return canonical_hash({k: v for k, v in body.items() if k != "integrity"})


def create_cost_lock(
    decision: PolicyDecision,
    estimate: CostEstimate,
    plan: NormalizedPlan,
    config: Config,
    commit: str,
    execution_id: str,
    stack: str | None = None,
) -> dict:
    if decision.status is not Status.PASS:
        raise CostLockError(
            "Refusing to create a cost lock for a non-PASS decision",
            detail=f"status={decision.status.value}",
        )

    if not estimate.is_authoritative and not config.cost_estimation.allow_non_authoritative_lock:
        raise CostLockError(
            f"Refusing to create a cost lock from non-authoritative estimator "
            f"'{estimate.estimator}'",
            detail="Only Infracost results may approve a deployment.",
        )

    body = {
        "schema_version": SCHEMA_VERSION,
        "lock_id": str(uuid.uuid4()),
        "status": "APPROVED",
        # Which Terraform root this authorises. A lock for one stack must never
        # be accepted for another.
        "stack": stack,
        "commit": commit,
        "execution_id": execution_id,
        "timestamp": utc_now_iso(),
        "plan_fingerprint": plan.fingerprint(),
        "currency": estimate.currency,
        "estimated_previous_monthly_cost": as_float(estimate.previous_monthly_cost),
        "estimated_new_monthly_cost": as_float(estimate.new_monthly_cost),
        "estimated_incremental_monthly_cost": as_float(estimate.incremental_monthly_cost),
        "threshold": as_float(decision.threshold_value),
        "threshold_metric": decision.metric,
        "threshold_unit": decision.unit,
        "comparison": decision.comparison,
        "observed_value": as_float(decision.observed_value),
        "estimator": estimate.estimator,
        "estimator_version": estimate.estimator_version,
        "estimator_trust": estimate.trust.value,
        "coverage": estimate.coverage.to_dict(),
        "clouds": [c.value for c in plan.clouds],
        "resource_count": len(plan.cost_relevant_changes),
        "warnings": decision.warnings,
    }
    body["integrity"] = _integrity(body)
    return body


def write_cost_lock(lock: dict, config: Config) -> Path:
    output_dir = Path(config.cost_lock.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / LOCK_FILENAME
    path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return path


def load_cost_lock(path: str | Path) -> dict:
    lock_path = Path(path)
    if not lock_path.is_file():
        raise CostLockError(f"Cost lock not found: {lock_path}")
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CostLockError(f"Cost lock {lock_path} is not valid JSON", detail=str(exc)) from exc


def verify_cost_lock(
    lock: dict, plan: NormalizedPlan, config: Config, stack: str | None = None
) -> list[str]:
    """Return a list of problems. Empty means the lock is valid for this plan."""
    problems: list[str] = []

    if stack is not None and lock.get("stack") != stack:
        problems.append(
            f"Lock was issued for stack {lock.get('stack')!r} and cannot authorise "
            f"stack {stack!r}"
        )

    if lock.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"Unexpected lock schema_version {lock.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION})"
        )

    recorded_integrity = lock.get("integrity")
    if not recorded_integrity:
        problems.append("Lock has no integrity hash")
    elif recorded_integrity != _integrity(lock):
        problems.append("Lock integrity hash does not match its contents (tampered or edited)")

    if lock.get("status") != "APPROVED":
        problems.append(f"Lock status is {lock.get('status')!r}, expected APPROVED")

    if lock.get("estimator_trust") != "AUTHORITATIVE" and not config.cost_estimation.allow_non_authoritative_lock:
        problems.append(
            f"Lock was produced by a non-authoritative estimator "
            f"({lock.get('estimator')!r})"
        )

    if config.cost_lock.bind_to_plan_fingerprint:
        current = plan.fingerprint()
        recorded = lock.get("plan_fingerprint")
        if recorded != current:
            problems.append(
                "Terraform change has been modified since approval; a new cost "
                f"estimate is required (lock={recorded}, current={current})"
            )

    if as_float(config.threshold.value) != lock.get("threshold"):
        problems.append(
            f"Threshold has changed since approval "
            f"(lock={lock.get('threshold')}, current={as_float(config.threshold.value)})"
        )

    if lock.get("threshold_metric") != config.threshold.metric:
        problems.append(
            f"Threshold metric has changed since approval "
            f"(lock={lock.get('threshold_metric')!r}, current={config.threshold.metric!r})"
        )

    return problems
