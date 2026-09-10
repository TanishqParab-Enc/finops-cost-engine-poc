"""finops command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .cost.factory import build_estimator
from .errors import FinOpsError
from .gate import GateRequest, run_gate, write_artifacts
from .plan.detector import detect_changes
from .plan.normalizer import normalize_plan_file
from .report.markdown import render_console, render_markdown

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to finops-policy.yaml", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finops",
        description="Shift-left FinOps cost governance gate for Terraform pull requests.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    detect = sub.add_parser(
        "detect-changes", help="Does this PR contain infrastructure changes?"
    )
    _add_config_arg(detect)
    detect.add_argument("--base", required=True, help="Base git ref")
    detect.add_argument("--head", default="HEAD", help="Head git ref")
    detect.add_argument("--repo-dir", default=".", help="Repository directory")
    detect.add_argument("--json", action="store_true", help="Emit JSON")

    analyze = sub.add_parser("analyze", help="Run the full cost gate")
    _add_config_arg(analyze)
    analyze.add_argument("--plan", required=True, help="Proposed Terraform plan JSON")
    analyze.add_argument(
        "--baseline-plan",
        default=None,
        help="Baseline Terraform plan JSON. Omit for a greenfield stack.",
    )
    analyze.add_argument(
        "--action-plan",
        default=None,
        help=(
            "Real (non-hermetic) plan of this same change against the actual "
            "deployed target state - labels which resources this PR genuinely "
            "changes in the resource-level breakdown. Never used for pricing."
        ),
    )
    analyze.add_argument(
        "--require-baseline",
        action="store_true",
        help=(
            "Fail closed when no baseline plan document was produced at all - "
            "i.e. the stack's expected remote backend could not be read. An "
            "accessible backend with no deployed state still produces an empty "
            "baseline document and prices as a $0 greenfield baseline."
        ),
    )
    analyze.add_argument("--commit", default="", help="Commit SHA for the lock artifact")
    analyze.add_argument("--execution-id", default="", help="CI/CD execution id")
    analyze.add_argument(
        "--infracost-json",
        default=None,
        help="Recorded Infracost JSON (estimator: infracost_fixture)",
    )
    analyze.add_argument(
        "--baseline-infracost-json",
        default=None,
        help="Recorded baseline Infracost JSON (estimator: infracost_fixture)",
    )
    analyze.add_argument("--json", action="store_true", help="Emit the gate result as JSON")
    analyze.add_argument("--markdown", action="store_true", help="Emit the PR comment markdown")
    analyze.add_argument("--stack", default=None, help="Stack this evaluation belongs to")
    analyze.add_argument(
        "--no-cost-lock",
        action="store_true",
        help="Never write a cost lock (stacks that cannot be deployed)",
    )

    normalize = sub.add_parser("normalize-plan", help="Show the normalised plan")
    _add_config_arg(normalize)
    normalize.add_argument("--plan", required=True)

    verify = sub.add_parser("verify-lock", help="Verify a cost lock against a plan")
    _add_config_arg(verify)
    verify.add_argument("--lock", required=True, help="Path to cost-lock.json")
    verify.add_argument("--plan", required=True, help="Terraform plan JSON to verify against")
    verify.add_argument("--stack", default=None, help="Stack the lock must authorise")

    create_exc = sub.add_parser(
        "create-exception",
        help="Create a peer-approved budget exception for an over-threshold change",
    )
    _add_config_arg(create_exc)
    create_exc.add_argument("--result", required=True, help="Path to gate-result.json (must be FAIL)")
    create_exc.add_argument("--plan", required=True, help="Terraform plan JSON the exception binds to")
    create_exc.add_argument("--pr", required=True, type=int, help="Pull request number")
    create_exc.add_argument("--head-sha", required=True, help="Pull request head commit SHA")
    create_exc.add_argument("--approver", required=True, help="GitHub login of the approving peer")
    create_exc.add_argument("--justification", required=True, help="Why the overspend is accepted")
    create_exc.add_argument(
        "--max-incremental-cost",
        type=float,
        default=None,
        help="Cost ceiling; re-evaluation above this invalidates the exception",
    )
    create_exc.add_argument("--ttl-days", type=int, default=None, help="Lifetime in days")
    create_exc.add_argument("--stack", default=None, help="Stack this exception authorises")
    create_exc.add_argument(
        "--terraform-dir", default=None, help="Terraform root this exception authorises"
    )
    create_exc.add_argument("--out", required=True, help="Where to write the exception record")

    verify_exc = sub.add_parser(
        "verify-exception",
        help="Verify a budget exception against a freshly computed plan and estimate",
    )
    _add_config_arg(verify_exc)
    verify_exc.add_argument("--exception", required=True, help="Path to the exception record")
    verify_exc.add_argument("--plan", required=True, help="Terraform plan JSON to verify against")
    verify_exc.add_argument("--estimate", required=True, help="Path to cost-estimate.json")
    verify_exc.add_argument("--pr", type=int, default=None, help="Pull request number")
    verify_exc.add_argument("--head-sha", default=None, help="Pull request head commit SHA")
    verify_exc.add_argument("--pr-author", default=None, help="Pull request author login")
    verify_exc.add_argument(
        "--reviews",
        default=None,
        help="JSON file of GitHub pull request reviews (live API output)",
    )
    verify_exc.add_argument("--verified-commit", default=None, help="Commit being verified")
    verify_exc.add_argument("--stack", default=None, help="Stack the exception must authorise")

    authorize = sub.add_parser(
        "authorize-deployment",
        help="Compute finops_decision/deployment_authorization for a trusted-main deploy",
    )
    authorize.add_argument("--exit-code", required=True, type=int, help="finops analyze exit code")
    authorize.add_argument(
        "--exception-valid", action="store_true",
        help="A fresh, peer-review-backed exception re-validated for this exact change",
    )
    authorize.add_argument(
        "--lock-not-verified", action="store_true",
        help="The cost lock failed re-verification against the fresh plan (normal/PASS path only)",
    )
    authorize.add_argument("--json", action="store_true")

    approve = sub.add_parser(
        "approve",
        help="Record an APPROVE/REJECT decision for a BLOCKed evaluation",
    )
    _add_config_arg(approve)
    approve.add_argument(
        "--action", required=True, choices=["approve", "reject"],
        help="The human's explicit choice",
    )
    approve.add_argument("--result", required=True, help="Path to gate-result.json (must be FAIL)")
    approve.add_argument("--plan", required=True, help="Terraform plan JSON the approval binds to")
    approve.add_argument(
        "--pr", type=int, default=None,
        help="Pull request number (omit for a workflow_dispatch greenfield run)",
    )
    approve.add_argument("--head-sha", required=True, help="Pull request head commit SHA")
    approve.add_argument("--stack", required=True, help="Stack this approval authorises")
    approve.add_argument(
        "--terraform-dir", required=True, help="Terraform root this approval authorises"
    )
    approve.add_argument(
        "--run-event", required=True,
        help="GitHub-attested github.event_name of the run (must be pull_request)",
    )
    approve.add_argument(
        "--approver", required=True,
        help="Identity recorded as having approved (the configured FINOPS_APPROVER). The "
             "real authorisation check already happened via the finops-cost-approval "
             "Environment's required reviewer, not this value.",
    )
    approve.add_argument(
        "--max-incremental-cost", type=float, default=None, help="Approved cost ceiling"
    )
    approve.add_argument("--ttl-days", type=int, default=None, help="Lifetime in days")
    approve.add_argument("--out", default=None, help="Where to write the approval record")
    approve.add_argument("--json", action="store_true")

    approval_verify = sub.add_parser(
        "approval-verify",
        help="Re-verify an environment-gated approval against a plan and estimate",
    )
    _add_config_arg(approval_verify)
    approval_verify.add_argument(
        "--decision", required=True, help="Path to the approval record"
    )
    approval_verify.add_argument("--plan", required=True, help="Terraform plan JSON")
    approval_verify.add_argument("--estimate", required=True, help="cost-estimate.json")
    approval_verify.add_argument("--pr", type=int, default=None, help="Pull request number")
    approval_verify.add_argument("--head-sha", default=None, help="Approved PR head commit SHA")
    approval_verify.add_argument("--stack", default=None, help="Stack being deployed")
    approval_verify.add_argument("--terraform-dir", default=None, help="Terraform root being applied")
    approval_verify.add_argument(
        "--run-event", default=None, help="Attested event of the approving run (must be pull_request)"
    )
    approval_verify.add_argument("--json", action="store_true")

    return parser


def _cmd_detect_changes(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = detect_changes(config.change_detection, args.base, args.head, args.repo_dir)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif result.has_infrastructure_changes:
        print(f"Infrastructure changes detected ({len(result.infrastructure_files)} file(s)):")
        for path in result.infrastructure_files:
            print(f"  {path}")
    else:
        print("No infrastructure changes detected.")
    return EXIT_PASS


def _cmd_analyze(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    output_dir = Path(config.cost_lock.output_dir)

    estimator = build_estimator(
        config,
        artifact_dir=output_dir,
        proposed_fixture=Path(args.infracost_json) if args.infracost_json else None,
        baseline_fixture=(
            Path(args.baseline_infracost_json) if args.baseline_infracost_json else None
        ),
    )

    result = run_gate(
        GateRequest(
            proposed_plan=Path(args.plan),
            baseline_plan=Path(args.baseline_plan) if args.baseline_plan else None,
            action_plan=Path(args.action_plan) if args.action_plan else None,
            require_baseline=args.require_baseline,
            commit=args.commit,
            execution_id=args.execution_id,
            stack=args.stack,
            allow_cost_lock=not args.no_cost_lock,
        ),
        config,
        estimator,
    )

    written = write_artifacts(result, config)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif args.markdown:
        print(render_markdown(result), end="")
    else:
        print(render_console(result))
        print()
        for label, path in written.items():
            print(f"  {label:8s} -> {path}")

    return result.exit_code


def _cmd_normalize_plan(args: argparse.Namespace) -> int:
    plan = normalize_plan_file(args.plan)
    print(json.dumps(plan.to_dict(), indent=2))
    return EXIT_PASS


def _cmd_verify_lock(args: argparse.Namespace) -> int:
    from .lock.cost_lock import load_cost_lock, verify_cost_lock

    config = load_config(args.config)
    lock = load_cost_lock(args.lock)
    plan = normalize_plan_file(args.plan)
    problems = verify_cost_lock(lock, plan, config, stack=args.stack)

    if problems:
        print("Cost lock is INVALID for this plan:")
        for problem in problems:
            print(f"  - {problem}")
        return EXIT_FAIL

    print("Cost lock is valid.")
    print(f"  lock_id          : {lock.get('lock_id')}")
    print(f"  approved cost    : {lock.get('estimated_incremental_monthly_cost')} {lock.get('currency')}/month")
    print(f"  threshold        : {lock.get('threshold')} ({lock.get('threshold_metric')})")
    print(f"  plan fingerprint : {lock.get('plan_fingerprint')}")
    return EXIT_PASS


def _rebuild_estimate(estimate_path: str):
    """Reload a cost-estimate.json artifact into a CostEstimate."""
    return _rebuild_estimate_from_dict(
        json.loads(Path(estimate_path).read_text(encoding="utf-8"))
    )


def _cmd_create_exception(args: argparse.Namespace) -> int:
    from .lock.exception import create_exception
    from .models import PolicyDecision, Status, money
    from .plan.normalizer import load_plan_json

    config = load_config(args.config)
    result_raw = json.loads(Path(args.result).read_text(encoding="utf-8"))
    if result_raw.get("status") != Status.FAIL.value:
        print(
            f"Refusing to create an exception: gate status is "
            f"{result_raw.get('status')!r}, expected FAIL."
        )
        return EXIT_ERROR

    policy_raw = result_raw.get("policy") or {}
    cost_raw = result_raw.get("cost") or {}
    decision = PolicyDecision(
        status=Status.FAIL,
        metric=policy_raw.get("metric", config.threshold.metric),
        unit=policy_raw.get("unit", config.threshold.unit),
        observed_value=money(policy_raw.get("observed_value")),
        threshold_value=money(policy_raw.get("threshold_value")),
        currency=policy_raw.get("currency", config.threshold.currency),
        comparison=policy_raw.get("comparison", config.threshold.comparison),
    )
    estimate = _rebuild_estimate_from_dict(cost_raw)
    plan = normalize_plan_file(args.plan)
    plan_doc = load_plan_json(args.plan)

    record = create_exception(
        decision,
        estimate,
        plan,
        plan_doc,
        config,
        pr_number=args.pr,
        head_sha=args.head_sha,
        approver=args.approver,
        justification=args.justification,
        stack=args.stack,
        terraform_dir=args.terraform_dir,
        max_incremental_cost=args.max_incremental_cost,
        ttl_days=args.ttl_days,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"Budget exception written to {out}")
    print(f"  exception_id           : {record['exception_id']}")
    print(f"  finops_decision        : {record['finops_decision']}  (unchanged)")
    print(f"  approved incremental   : {record['approved_incremental_cost']} {record['currency']}/month")
    print(f"  ceiling                : {record['max_incremental_cost']} {record['currency']}/month")
    print(f"  expires_at             : {record['expires_at']}")
    return EXIT_PASS


def _rebuild_estimate_from_dict(raw: dict):
    from .models import CostEstimate, EstimatorTrust, money

    return CostEstimate(
        currency=raw.get("currency", "USD"),
        estimator=raw.get("estimator", "unknown"),
        estimator_version=raw.get("estimator_version"),
        trust=EstimatorTrust(raw.get("trust", EstimatorTrust.NON_AUTHORITATIVE.value)),
        previous_monthly_cost=money(raw.get("previous_monthly_cost")),
        new_monthly_cost=money(raw.get("new_monthly_cost")),
        incremental_monthly_cost=money(raw.get("incremental_monthly_cost")),
    )


def _cmd_verify_exception(args: argparse.Namespace) -> int:
    from .lock.exception import (
        build_approval_record,
        load_exception,
        verify_exception,
        write_approval,
    )
    from .plan.normalizer import load_plan_json

    config = load_config(args.config)
    record = load_exception(args.exception)
    plan = normalize_plan_file(args.plan)
    plan_doc = load_plan_json(args.plan)
    estimate = _rebuild_estimate(args.estimate)

    reviews = None
    if args.reviews:
        reviews_raw = json.loads(Path(args.reviews).read_text(encoding="utf-8"))
        reviews = reviews_raw if isinstance(reviews_raw, list) else reviews_raw.get("reviews") or []

    problems = verify_exception(
        record,
        plan,
        plan_doc,
        estimate,
        config,
        pr_number=args.pr,
        pr_author=args.pr_author,
        head_sha=args.head_sha,
        stack=args.stack,
        reviews=reviews,
    )

    approval = build_approval_record(
        record,
        problems,
        pr_number=args.pr,
        head_sha=args.head_sha,
        verified_commit=args.verified_commit,
    )
    write_approval(approval, config)

    # Append to the PR comment rather than regenerating it: the FAIL verdict
    # above must stay visible alongside the approval.
    comment = Path(config.cost_lock.output_dir) / "pr-comment.md"
    if comment.is_file():
        from .report.markdown import render_exception_banner

        with comment.open("a", encoding="utf-8") as handle:
            handle.write(render_exception_banner(approval))

    if problems:
        print("Budget exception is NOT valid for this change:")
        for problem in problems:
            print(f"  - {problem}")
        return EXIT_FAIL

    print("Budget exception is valid.")
    print(f"  finops_decision      : {approval['finops_decision']}  (unchanged)")
    print(f"  exception_approval   : {approval['exception_approval']}")
    print(f"  exception_id         : {approval['exception_id']}")
    print(f"  approver             : {approval['approver']}")
    print(f"  approved incremental : {approval['approved_incremental_cost']} {approval['currency']}/month")
    print(f"  ceiling              : {approval['max_incremental_cost']} {approval['currency']}/month")
    print(f"  expires_at           : {approval['expires_at']}")
    return EXIT_PASS


def _cmd_authorize_deployment(args: argparse.Namespace) -> int:
    from .gate import evaluate_approval

    states = evaluate_approval(
        analyze_exit_code=args.exit_code,
        approval_action="approve" if args.exception_valid else None,
        lock_verified=not args.lock_not_verified,
    )

    if args.json:
        print(json.dumps(states))
    else:
        for key, value in states.items():
            print(f"{key}: {value}")

    return EXIT_PASS if states["deployment_authorization"] == "AUTHORIZED" else EXIT_FAIL


def _rebuild_decision_from_result(result_raw: dict, config):
    """Rebuild the FAIL PolicyDecision recorded in a gate-result.json."""
    from .models import PolicyDecision, Status, money

    policy_raw = result_raw.get("policy") or {}
    return PolicyDecision(
        status=Status.FAIL,
        metric=policy_raw.get("metric", config.threshold.metric),
        unit=policy_raw.get("unit", config.threshold.unit),
        observed_value=money(policy_raw.get("observed_value")),
        threshold_value=money(policy_raw.get("threshold_value")),
        currency=policy_raw.get("currency", config.threshold.currency),
        comparison=policy_raw.get("comparison", config.threshold.comparison),
    )


def _cmd_approve(args: argparse.Namespace) -> int:
    """Record the human APPROVE/REJECT choice.

    The identity check has already happened by the time this runs: it is
    only ever invoked from the ``finops-approval`` job, which GitHub starts
    only after the ``finops-cost-approval`` Environment's required reviewer
    clicks Approve on this exact run - a Reject prevents these steps from
    running at all. This function therefore only re-checks the channel
    (must be a pull_request or workflow_dispatch run) and the evaluation
    itself (must really be a FAIL), never an actor - GitHub already is that
    check. Rejection is a deliberate business outcome, so it exits 0 rather
    than masquerading as a system failure; it simply mints no record, and
    nothing downstream can treat the absence of a record as authorisation.
    """
    from .gate import (
        APPROVAL_APPROVED,
        APPROVAL_REJECTED,
        REJECTION_MESSAGE,
    )
    from .lock.exception import create_exception
    from .models import Status, as_float
    from .plan.normalizer import load_plan_json

    config = load_config(args.config)

    if args.run_event not in ("pull_request", "workflow_dispatch"):
        print(
            f"::error::A decision must come from a pull_request or workflow_dispatch "
            f"run, not {args.run_event!r}.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    result_raw = json.loads(Path(args.result).read_text(encoding="utf-8"))
    if result_raw.get("status") != Status.FAIL.value:
        print(
            f"Refusing to decide: gate status is {result_raw.get('status')!r}, "
            f"expected FAIL (nothing to approve or reject).",
            file=sys.stderr,
        )
        return EXIT_ERROR

    decision = _rebuild_decision_from_result(result_raw, config)
    estimate = _rebuild_estimate_from_dict(result_raw.get("cost") or {})
    incremental = as_float(estimate.incremental_monthly_cost) or 0.0
    threshold = as_float(decision.threshold_value)

    if args.action == "reject":
        payload = {
            "message": REJECTION_MESSAGE,
            "pr": args.pr,
            "stack": args.stack,
            "terraform_dir": args.terraform_dir,
            "incremental_monthly_cost": incremental,
            "threshold": threshold,
            "currency": estimate.currency,
            "finops_decision": "BLOCK",
            "approval_status": APPROVAL_REJECTED,
            "deployment_authorization": "DENIED",
            "rejected_by": args.approver,
        }
        if args.json:
            print(json.dumps(payload))
        else:
            print(REJECTION_MESSAGE)
            print(f"PR:                       {'#' + str(args.pr) if args.pr is not None else 'N/A (workflow_dispatch)'}")
            print(f"Stack:                    {args.stack}")
            print(f"Terraform root:           {args.terraform_dir}")
            print(f"Incremental monthly cost: {estimate.currency} {incremental}")
            print(f"Threshold:                {estimate.currency} {threshold}")
            print(f"Approval:                 {APPROVAL_REJECTED} by {args.approver}")
            print("Deployment authorization: DENIED")
        return EXIT_PASS

    plan = normalize_plan_file(args.plan)
    plan_doc = load_plan_json(args.plan)

    record = create_exception(
        decision,
        estimate,
        plan,
        plan_doc,
        config,
        pr_number=args.pr,
        head_sha=args.head_sha,
        approver=args.approver,
        justification=(
            f"Cost estimate explicitly approved by {args.approver} via the "
            f"finops-cost-approval GitHub Environment on the FinOps Cost Gate workflow."
        ),
        stack=args.stack,
        terraform_dir=args.terraform_dir,
        max_incremental_cost=args.max_incremental_cost,
        ttl_days=args.ttl_days,
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2), encoding="utf-8")

    payload = {
        "finops_decision": "BLOCK",
        "approval_status": APPROVAL_APPROVED,
        "deployment_authorization": "AUTHORIZED",
        "pr": args.pr,
        "stack": args.stack,
        "terraform_dir": args.terraform_dir,
        "exception_id": record["exception_id"],
        "approver": record["approver"],
        "approved_incremental_cost": record["approved_incremental_cost"],
        "max_incremental_cost": record["max_incremental_cost"],
        "threshold": threshold,
        "expires_at": record["expires_at"],
    }
    if args.json:
        print(json.dumps(payload))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return EXIT_PASS


def _cmd_approval_verify(args: argparse.Namespace) -> int:
    """Re-verify an environment-gated approval record against a plan and
    estimate. Not called by the workflow itself (the finops-approval job
    consumes the same-run artifacts it mints directly), but kept as an
    independently testable, standalone verification path."""
    from .gate import evaluate_approval
    from .lock.exception import load_exception, verify_environment_approval
    from .plan.normalizer import load_plan_json

    config = load_config(args.config)
    record = load_exception(args.decision)
    plan = normalize_plan_file(args.plan)
    plan_doc = load_plan_json(args.plan)
    estimate = _rebuild_estimate(args.estimate)

    problems = verify_environment_approval(
        record,
        plan,
        plan_doc,
        estimate,
        config,
        pr_number=args.pr,
        head_sha=args.head_sha,
        stack=args.stack,
        terraform_dir=args.terraform_dir,
        run_event=args.run_event,
    )

    states = evaluate_approval(
        analyze_exit_code=1, approval_action="approve", approval_problems=problems
    )

    if args.json:
        print(json.dumps({**states, "problems": problems}))
    else:
        for key, value in states.items():
            print(f"{key}: {value}")
        for problem in problems:
            print(f"  - {problem}")

    return EXIT_PASS if states["deployment_authorization"] == "AUTHORIZED" else EXIT_FAIL


_COMMANDS = {
    "detect-changes": _cmd_detect_changes,
    "analyze": _cmd_analyze,
    "normalize-plan": _cmd_normalize_plan,
    "verify-lock": _cmd_verify_lock,
    "create-exception": _cmd_create_exception,
    "verify-exception": _cmd_verify_exception,
    "authorize-deployment": _cmd_authorize_deployment,
    "approve": _cmd_approve,
    "approval-verify": _cmd_approval_verify,
}


def main(argv: list[str] | None = None) -> int:
    # PR comments contain non-ASCII status markers; legacy Windows consoles
    # default to cp1252 and would otherwise raise UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except FinOpsError as exc:
        print(f"[{exc.category.value}] {exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  {exc.detail}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
