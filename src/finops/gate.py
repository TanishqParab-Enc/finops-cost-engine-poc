"""Component H - the CI/CD gate orchestration.

Exit codes:
  0  PASS   - within threshold, cost locked, pipeline continues
  1  FAIL   - threshold exceeded, no lock, peer review required
  2  ERROR  - cost could not be trusted, fail safe
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from .ai import factory as ai_factory
from .config import Config
from .cost.base import EstimationRequest, CostEstimator
from .errors import FinOpsError
from .lock.cost_lock import create_cost_lock, write_cost_lock
from .models import GateResult, NormalizedPlan, Status
from .plan.normalizer import normalize_plan_file
from .policy import engine as policy_engine


@dataclass
class GateRequest:
    proposed_plan: Path
    baseline_plan: Path | None = None
    commit: str = ""
    execution_id: str = ""
    stack: str | None = None
    # A lock authorises deployment. A stack that cannot be deployed must not
    # mint one just because it priced under the threshold.
    allow_cost_lock: bool = True


def _resolve_identity(request: GateRequest) -> tuple[str, str]:
    commit = (
        request.commit
        or os.environ.get("GITHUB_SHA")
        or os.environ.get("GIT_COMMIT")
        or "unknown"
    )
    execution_id = (
        request.execution_id
        or os.environ.get("GITHUB_RUN_ID")
        or os.environ.get("BUILD_NUMBER")
        or str(uuid.uuid4())
    )
    return commit, execution_id


def run_gate(request: GateRequest, config: Config, estimator: CostEstimator) -> GateResult:
    commit, execution_id = _resolve_identity(request)
    result = GateResult(status=Status.ERROR, commit=commit, execution_id=execution_id)

    plan: NormalizedPlan | None = None
    errors: list[FinOpsError] = []

    try:
        plan = normalize_plan_file(request.proposed_plan)
        result.plan = plan
    except FinOpsError as exc:
        result.errors.append(exc.to_dict())
        return result

    try:
        estimator.preflight()
        estimate = estimator.estimate(
            EstimationRequest(
                proposed_plan_json=request.proposed_plan,
                baseline_plan_json=request.baseline_plan,
                normalized_plan=plan,
                currency=config.threshold.currency,
            )
        )
        result.estimate = estimate
    except FinOpsError as exc:
        result.errors.append(exc.to_dict())
        errors.append(exc)
        estimate = None

    if estimate is None:
        decision = policy_engine.evaluate(
            estimate=_empty_estimate(config), config=config, upstream_errors=errors
        )
        result.decision = decision
        result.status = Status.ERROR
        return result

    decision = policy_engine.evaluate(estimate, config)
    result.decision = decision
    result.status = decision.status
    result.errors.extend(decision.blocking_errors)

    analysis, ai_error = ai_factory.analyze(plan, estimate, decision, config.ai)
    result.ai = analysis
    if ai_error and config.ai.required and config.fail_safe.blocks("on_ai_failure"):
        result.status = Status.ERROR
        result.errors.append(ai_error.to_dict())
        return result

    if result.status is Status.PASS and request.allow_cost_lock:
        lock = create_cost_lock(
            decision, estimate, plan, config, commit, execution_id, stack=request.stack
        )
        write_cost_lock(lock, config)
        result.cost_lock = lock

    return result


def _empty_estimate(config: Config):
    from decimal import Decimal

    from .models import CostEstimate, EstimatorTrust

    return CostEstimate(
        currency=config.threshold.currency,
        estimator="none",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal("0"),
        new_monthly_cost=Decimal("0"),
        incremental_monthly_cost=Decimal("0"),
    )


def write_artifacts(result: GateResult, config: Config) -> dict[str, Path]:
    from .report.markdown import render_markdown

    output_dir = Path(config.cost_lock.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    result_path = output_dir / "gate-result.json"
    result_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    written["result"] = result_path

    comment_path = output_dir / "pr-comment.md"
    comment_path.write_text(render_markdown(result), encoding="utf-8")
    written["comment"] = comment_path

    if result.estimate:
        cost_path = output_dir / "cost-estimate.json"
        cost_path.write_text(json.dumps(result.estimate.to_dict(), indent=2), encoding="utf-8")
        written["cost"] = cost_path

    if result.plan:
        plan_path = output_dir / "normalized-plan.json"
        plan_path.write_text(json.dumps(result.plan.to_dict(), indent=2), encoding="utf-8")
        written["plan"] = plan_path

    return written


def finops_decision_label(analyze_exit_code: int) -> str:
    """PASS/BLOCK vocabulary for the decision itself. Independent of, and
    never influenced by, deployment authorisation - an approved exception
    changes what may deploy, never what the decision was."""
    return "PASS" if analyze_exit_code == 0 else "BLOCK"


def authorize_deployment(
    *, analyze_exit_code: int, exception_valid: bool | None = None, lock_verified: bool = True,
) -> str:
    """AUTHORIZED or DENIED for a trusted `main` deployment.

    Exactly two paths authorise deployment:
      1. Normal: the fresh analyze run PASSed (exit_code 0) and, for a
         deployable stack, its cost lock re-verified against the fresh plan.
      2. Exception: the fresh analyze run was BLOCKed (exit_code 1) but a
         freshly re-validated, peer-review-backed exception covers this
         exact PR/head SHA/stack/cost. Re-validation (non-author reviewer,
         allow-list, APPROVED state, expiry, integrity, cost ceiling, ...)
         happens in verify_exception; this function only consumes its
         boolean result.
    Anything else - no exception, an invalid/stale one, or exit_code 2
    (cost could not be trusted, e.g. a non-authoritative/mocked estimate) -
    is DENIED. finops_decision is never rewritten by this function: a BLOCK
    that is AUTHORIZED via exception is still a BLOCK.
    """
    if analyze_exit_code == 0:
        return "AUTHORIZED" if lock_verified else "DENIED"
    if analyze_exit_code == 1 and exception_valid:
        return "AUTHORIZED"
    return "DENIED"


REJECTION_MESSAGE = "Deployment cancelled because the cost estimate was rejected."

APPROVAL_NOT_REQUIRED = "NOT_REQUIRED"
APPROVAL_PENDING = "PENDING"
APPROVAL_APPROVED = "APPROVED"
APPROVAL_REJECTED = "REJECTED"


def evaluate_approval(
    *,
    analyze_exit_code: int,
    approval_action: str | None = None,
    approval_problems: list | None = None,
    lock_verified: bool = True,
) -> dict:
    """The three states the pipeline reports, kept deliberately separate.

    ``finops_decision`` is derived only from the cost evaluation and is never
    rewritten by an approval - an approved overspend is still a BLOCK. Only
    ``deployment_authorization`` moves.

    ``approval_action`` is the human's explicit choice ('approve'/'reject')
    from a workflow_dispatch run; ``approval_problems`` is the result of
    re-verifying that approval's bindings. An approval that fails any binding
    is not an approval - it leaves the change PENDING and DENIED rather than
    silently authorising it.
    """
    decision = finops_decision_label(analyze_exit_code)

    if analyze_exit_code == 0:
        authorized = lock_verified
        return {
            "finops_decision": decision,
            "approval_status": APPROVAL_NOT_REQUIRED,
            "deployment_authorization": "AUTHORIZED" if authorized else "DENIED",
        }

    action = (approval_action or "").strip().lower()

    if action == "reject":
        return {
            "finops_decision": decision,
            "approval_status": APPROVAL_REJECTED,
            "deployment_authorization": "DENIED",
            "message": REJECTION_MESSAGE,
        }

    # exit_code 2 means the cost itself could not be trusted; no approval of a
    # number we could not establish is meaningful.
    if action == "approve" and analyze_exit_code == 1 and not approval_problems:
        return {
            "finops_decision": decision,
            "approval_status": APPROVAL_APPROVED,
            "deployment_authorization": "AUTHORIZED",
        }

    return {
        "finops_decision": decision,
        "approval_status": APPROVAL_PENDING,
        "deployment_authorization": "DENIED",
    }
