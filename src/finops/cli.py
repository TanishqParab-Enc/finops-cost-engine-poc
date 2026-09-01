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

    normalize = sub.add_parser("normalize-plan", help="Show the normalised plan")
    _add_config_arg(normalize)
    normalize.add_argument("--plan", required=True)

    verify = sub.add_parser("verify-lock", help="Verify a cost lock against a plan")
    _add_config_arg(verify)
    verify.add_argument("--lock", required=True, help="Path to cost-lock.json")
    verify.add_argument("--plan", required=True, help="Terraform plan JSON to verify against")

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
            commit=args.commit,
            execution_id=args.execution_id,
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
    problems = verify_cost_lock(lock, plan, config)

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


_COMMANDS = {
    "detect-changes": _cmd_detect_changes,
    "analyze": _cmd_analyze,
    "normalize-plan": _cmd_normalize_plan,
    "verify-lock": _cmd_verify_lock,
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
