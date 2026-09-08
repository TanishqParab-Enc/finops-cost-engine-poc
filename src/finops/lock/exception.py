"""Budget exception - the audited override for an over-threshold change.

A FAIL is never rewritten into a PASS. Instead an exception is a *second*,
separate state: the FinOps decision stays FAIL and the exception records that a
human accepted that specific overspend. Both facts travel together.

The record is bound to the exact change it approved. Two independent bindings
are used because neither is sufficient alone:

* ``plan_fingerprint`` - the cost-relevant resource shape.
* ``resolved_variables_hash`` - every resolved Terraform input. The resource
  fingerprint cannot see provider region (main.tf sets ``region = var.region``,
  so the plan records a reference, not a constant, and the normalizer resolves
  region to null on both sides). A region swap is materially expensive and would
  otherwise slip through.

Repo content can never authorise itself: the approving review is fetched from
the live GitHub API by the caller and validated here against the record.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..errors import PolicyError
from ..models import (
    CostEstimate,
    NormalizedPlan,
    PolicyDecision,
    Status,
    as_float,
    canonical_hash,
    money,
    utc_now_iso,
)

SCHEMA_VERSION = "1.0"
APPROVAL_FILENAME = "exception-approval.json"


class BudgetExceptionError(PolicyError):
    pass


def _integrity(body: dict) -> str:
    return canonical_hash({k: v for k, v in body.items() if k != "integrity"})


def _parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BudgetExceptionError(f"Exception field {field!r} is missing or not a timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BudgetExceptionError(
            f"Exception field {field!r} is not a valid ISO-8601 timestamp", detail=value
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolved_variables_hash(plan_doc: dict) -> str:
    """Hash every resolved Terraform input, including region.

    Uses the plan's own ``variables`` block, which Terraform populates for all
    declared variables - defaults included - so a value that is only set by a
    default is still covered.
    """
    if not isinstance(plan_doc, dict):
        raise BudgetExceptionError("Terraform plan JSON must be an object")
    block = plan_doc.get("variables")
    if not block:
        raise BudgetExceptionError(
            "Terraform plan JSON exposes no resolved variables",
            detail="Cannot bind an exception to a configuration that cannot be read.",
        )
    return canonical_hash({name: item.get("value") for name, item in block.items()})


def create_exception(
    decision: PolicyDecision,
    estimate: CostEstimate,
    plan: NormalizedPlan,
    plan_doc: dict,
    config: Config,
    *,
    pr_number: int,
    head_sha: str,
    approver: str,
    justification: str,
    stack: str | None = None,
    terraform_dir: str | None = None,
    max_incremental_cost: float | None = None,
    ttl_days: int | None = None,
) -> dict:
    if decision.status is not Status.FAIL:
        raise BudgetExceptionError(
            "Budget exceptions only apply to a FAIL decision",
            detail=f"status={decision.status.value}",
        )
    if not estimate.is_authoritative:
        raise BudgetExceptionError(
            f"Refusing to approve an exception from non-authoritative estimator "
            f"'{estimate.estimator}'"
        )
    if not justification.strip():
        raise BudgetExceptionError("A budget exception requires a written justification")

    approved = as_float(estimate.incremental_monthly_cost) or 0.0
    ceiling = float(max_incremental_cost) if max_incremental_cost is not None else approved
    if ceiling < approved:
        raise BudgetExceptionError(
            "max_incremental_cost cannot be lower than the approved incremental cost",
            detail=f"ceiling={ceiling}, approved={approved}",
        )
    headroom = config.exceptions.max_ceiling_ratio
    if approved > 0 and ceiling > approved * headroom:
        raise BudgetExceptionError(
            f"max_incremental_cost exceeds the permitted headroom of {headroom:g}x the "
            f"approved cost",
            detail=f"ceiling={ceiling}, approved={approved}",
        )

    ttl = int(ttl_days if ttl_days is not None else config.exceptions.max_ttl_days)
    if ttl < 1 or ttl > config.exceptions.max_ttl_days:
        raise BudgetExceptionError(
            f"Exception TTL must be between 1 and {config.exceptions.max_ttl_days} days",
            detail=f"ttl_days={ttl}",
        )

    created = datetime.now(timezone.utc)
    body = {
        "schema_version": SCHEMA_VERSION,
        "exception_id": str(uuid.uuid4()),
        "status": "APPROVED",
        "finops_decision": Status.FAIL.value,
        # Which Terraform root this authorises. An exception for one stack must
        # never be accepted for another.
        "stack": stack,
        "terraform_dir": terraform_dir,
        "pr": int(pr_number),
        "head_sha": head_sha,
        "plan_fingerprint": plan.fingerprint(),
        "resolved_variables_hash": resolved_variables_hash(plan_doc),
        "currency": estimate.currency,
        "approved_incremental_cost": approved,
        "max_incremental_cost": ceiling,
        "threshold_value": as_float(decision.threshold_value),
        "threshold_metric": decision.metric,
        "approver": approver,
        "justification": justification.strip(),
        "approved_at": created.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expires_at": (created + timedelta(days=ttl))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "estimator": estimate.estimator,
        "estimator_version": estimate.estimator_version,
        "estimator_trust": estimate.trust.value,
    }
    body["integrity"] = _integrity(body)
    return body


def load_exception(path: str | Path) -> dict:
    record_path = Path(path)
    if not record_path.is_file():
        raise BudgetExceptionError(f"Budget exception not found: {record_path}")
    text = record_path.read_text(encoding="utf-8")
    if record_path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise BudgetExceptionError(
                f"Budget exception {record_path} is not valid YAML", detail=str(exc)
            ) from exc
    else:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BudgetExceptionError(
                f"Budget exception {record_path} is not valid JSON", detail=str(exc)
            ) from exc
    if not isinstance(loaded, dict):
        raise BudgetExceptionError(f"Budget exception {record_path} must be a mapping")
    return loaded


def _authorising_review(
    record: dict,
    reviews: list[dict],
    pr_author: str | None,
    config: Config,
    problems: list[str],
) -> dict | None:
    """The review that authorises this exception, or None with problems appended."""
    allowlist = {a.strip().lower() for a in config.exceptions.approvers if a.strip()}
    if not allowlist:
        problems.append(
            "No approver allowlist is configured; refusing to accept any exception "
            "(set exceptions.approvers or FINOPS_APPROVERS)"
        )
        return None

    approvals = [r for r in reviews if str(r.get("state", "")).upper() == "APPROVED"]
    if not approvals:
        problems.append("No APPROVED pull request review found for this change")
        return None

    head_sha = record.get("head_sha")
    author = (pr_author or "").strip().lower()
    rejected: list[str] = []

    for review in approvals:
        login = str(((review.get("user") or {}).get("login") or "")).strip()
        low = login.lower()
        if config.exceptions.require_non_author_approval and author and low == author:
            rejected.append(f"{login}: self-approval by the pull request author is not permitted")
            continue
        if low not in allowlist:
            rejected.append(f"{login}: not in the approver allowlist")
            continue
        if review.get("commit_id") != head_sha:
            rejected.append(
                f"{login}: review approved {str(review.get('commit_id'))[:12]!r} but the "
                f"exception is bound to {str(head_sha)[:12]!r} (stale review)"
            )
            continue
        return review

    problems.append("No usable approval: " + "; ".join(rejected))
    return None


def _binding_problems(
    record: dict,
    plan: NormalizedPlan,
    plan_doc: dict,
    estimate: CostEstimate,
    config: Config,
    *,
    pr_number: int | None,
    head_sha: str | None,
    stack: str | None,
    terraform_dir: str | None,
    now: datetime | None,
) -> list[str]:
    """Everything that binds a record to one exact evaluation. Deliberately
    excludes the human-authorisation source, so the PR-review path and the
    workflow_dispatch path share one binding engine and can never drift."""
    problems: list[str] = []

    # Symmetric with create_exception: a test double or otherwise untrusted
    # estimator must never authorise a real deployment, even against an
    # otherwise-valid exception.
    if not estimate.is_authoritative:
        problems.append(
            f"Refusing to authorise from a non-authoritative estimator "
            f"'{estimate.estimator}'"
        )

    if stack is not None and record.get("stack") != stack:
        problems.append(
            f"Exception was approved for stack {record.get('stack')!r} and cannot "
            f"authorise stack {stack!r}"
        )

    if terraform_dir is not None and record.get("terraform_dir") != terraform_dir:
        problems.append(
            f"Exception was approved for Terraform root {record.get('terraform_dir')!r} "
            f"and cannot authorise {terraform_dir!r}"
        )

    if record.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"Unexpected exception schema_version {record.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION})"
        )

    recorded_integrity = record.get("integrity")
    if not recorded_integrity:
        problems.append("Exception has no integrity hash")
    elif recorded_integrity != _integrity(record):
        problems.append("Exception integrity hash does not match its contents (tampered or edited)")

    if record.get("status") != "APPROVED":
        problems.append(f"Exception status is {record.get('status')!r}, expected APPROVED")

    if record.get("finops_decision") != Status.FAIL.value:
        problems.append(
            "Exception does not preserve the original FinOps decision "
            f"(finops_decision={record.get('finops_decision')!r}, expected FAIL)"
        )

    # -- binding to the exact change ---------------------------------------
    current_fp = plan.fingerprint()
    if record.get("plan_fingerprint") != current_fp:
        problems.append(
            "Terraform change has been modified since approval "
            f"(exception={record.get('plan_fingerprint')}, current={current_fp})"
        )

    try:
        current_vars = resolved_variables_hash(plan_doc)
    except BudgetExceptionError as exc:
        problems.append(str(exc))
    else:
        if record.get("resolved_variables_hash") != current_vars:
            problems.append(
                "Resolved Terraform configuration has changed since approval "
                f"(exception={record.get('resolved_variables_hash')}, current={current_vars})"
            )

    # -- binding to cost ----------------------------------------------------
    ceiling = record.get("max_incremental_cost")
    observed = as_float(estimate.incremental_monthly_cost)
    if not isinstance(ceiling, (int, float)):
        problems.append("Exception has no numeric max_incremental_cost")
    elif observed is not None and money(observed) > money(ceiling):
        problems.append(
            f"Incremental cost {observed} exceeds the approved ceiling {ceiling} "
            f"{record.get('currency', '')}".strip()
        )

    if record.get("currency") != estimate.currency:
        problems.append(
            f"Currency has changed since approval "
            f"(exception={record.get('currency')!r}, current={estimate.currency!r})"
        )

    # -- binding to policy --------------------------------------------------
    if record.get("threshold_value") != as_float(config.threshold.value):
        problems.append(
            f"Threshold has changed since approval (exception={record.get('threshold_value')}, "
            f"current={as_float(config.threshold.value)})"
        )
    if record.get("threshold_metric") != config.threshold.metric:
        problems.append(
            f"Threshold metric has changed since approval "
            f"(exception={record.get('threshold_metric')!r}, current={config.threshold.metric!r})"
        )

    # -- freshness ----------------------------------------------------------
    moment = now or datetime.now(timezone.utc)
    try:
        approved_at = _parse_ts(record.get("approved_at"), "approved_at")
        expires_at = _parse_ts(record.get("expires_at"), "expires_at")
    except BudgetExceptionError as exc:
        problems.append(str(exc))
    else:
        if expires_at <= moment:
            problems.append(f"Exception expired at {record.get('expires_at')}")
        if expires_at - approved_at > timedelta(days=config.exceptions.max_ttl_days):
            problems.append(
                f"Exception lifetime exceeds the permitted {config.exceptions.max_ttl_days} days"
            )

    # -- binding to the pull request ----------------------------------------
    if pr_number is not None and record.get("pr") != int(pr_number):
        problems.append(
            f"Exception was approved for PR #{record.get('pr')}, but this change came "
            f"from PR #{pr_number}"
        )
    if head_sha is not None and record.get("head_sha") != head_sha:
        problems.append(
            f"Exception is bound to head {str(record.get('head_sha'))[:12]!r}, but the "
            f"pull request head is {str(head_sha)[:12]!r}"
        )

    return problems


def verify_exception(
    record: dict,
    plan: NormalizedPlan,
    plan_doc: dict,
    estimate: CostEstimate,
    config: Config,
    *,
    pr_number: int | None = None,
    pr_author: str | None = None,
    head_sha: str | None = None,
    stack: str | None = None,
    terraform_dir: str | None = None,
    reviews: list[dict] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return a list of problems. Empty means the exception authorises this change."""
    if not config.exceptions.enabled:
        return ["Budget exceptions are disabled by policy"]

    problems = _binding_problems(
        record, plan, plan_doc, estimate, config,
        pr_number=pr_number, head_sha=head_sha, stack=stack,
        terraform_dir=terraform_dir, now=now,
    )

    # -- authorisation (never satisfiable by repository content) ------------
    if config.exceptions.require_review_approval:
        if reviews is None:
            problems.append(
                "No pull request review data supplied; cannot authorise an exception"
            )
        else:
            review = _authorising_review(record, reviews, pr_author, config, problems)
            if review is not None:
                login = str(((review.get("user") or {}).get("login") or ""))
                recorded = str(record.get("approver") or "")
                if recorded.strip().lower() != login.strip().lower():
                    problems.append(
                        f"Exception names {recorded!r} as approver but the authorising "
                        f"review was submitted by {login!r}"
                    )

    return problems


def verify_environment_approval(
    record: dict,
    plan: NormalizedPlan,
    plan_doc: dict,
    estimate: CostEstimate,
    config: Config,
    *,
    pr_number: int | None = None,
    head_sha: str | None = None,
    stack: str | None = None,
    terraform_dir: str | None = None,
    run_event: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Same bindings as ``verify_exception``, but the human decision comes
    from a GitHub Actions Environment's required-reviewer protection rule
    (the ``finops-cost-approval`` Environment), reviewed in the SAME pipeline
    run that produced the evaluation - not a pull request review and not a
    separate ``workflow_dispatch`` run.

    There is deliberately no actor/approver check here. GitHub itself only
    starts the job that calls ``finops approve`` after the Environment's
    required reviewer clicks Approve on this exact run; a Reject prevents
    those steps from ever running. That makes the identity check GitHub's
    job, not this function's - duplicating it here would check nothing
    GitHub has not already enforced. The one channel check kept is
    ``run_event``: this must be a ``pull_request`` run, the only trigger this
    workflow ever gates with the Environment.
    """
    if not config.exceptions.enabled:
        return ["Budget exceptions are disabled by policy"]

    problems = _binding_problems(
        record, plan, plan_doc, estimate, config,
        pr_number=pr_number, head_sha=head_sha, stack=stack,
        terraform_dir=terraform_dir, now=now,
    )

    if run_event != "pull_request":
        problems.append(
            f"Approval must come from the pull request's own run, not {run_event!r}"
        )

    return problems


def build_approval_record(
    record: dict,
    problems: list[str],
    *,
    pr_number: int | None,
    head_sha: str | None,
    verified_commit: str | None = None,
) -> dict:
    """The audit artifact written next to the gate result."""
    approved = not problems
    return {
        "schema_version": SCHEMA_VERSION,
        "finops_decision": Status.FAIL.value,
        "exception_approval": "APPROVED" if approved else "REJECTED",
        "exception_id": record.get("exception_id"),
        "stack": record.get("stack"),
        "terraform_dir": record.get("terraform_dir"),
        "pr": pr_number if pr_number is not None else record.get("pr"),
        "head_sha": head_sha or record.get("head_sha"),
        "verified_commit": verified_commit,
        "approver": record.get("approver"),
        "justification": record.get("justification"),
        "approved_incremental_cost": record.get("approved_incremental_cost"),
        "max_incremental_cost": record.get("max_incremental_cost"),
        "threshold_value": record.get("threshold_value"),
        "threshold_metric": record.get("threshold_metric"),
        "currency": record.get("currency"),
        "plan_fingerprint": record.get("plan_fingerprint"),
        "resolved_variables_hash": record.get("resolved_variables_hash"),
        "approved_at": record.get("approved_at"),
        "expires_at": record.get("expires_at"),
        "verified_at": utc_now_iso(),
        "problems": problems,
    }


def write_approval(approval: dict, config: Config) -> Path:
    output_dir = Path(config.cost_lock.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / APPROVAL_FILENAME
    path.write_text(json.dumps(approval, indent=2), encoding="utf-8")
    return path
