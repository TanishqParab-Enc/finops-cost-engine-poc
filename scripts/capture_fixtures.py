"""Capture golden Infracost JSON fixtures from real runs.

Integration tests replay these files so the authoritative Infracost parser is
covered without a network call or an API key. Re-run this whenever the Infracost
schema or the example Terraform changes.

Requires: an authenticated Infracost CLI (`infracost auth login`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from finops.cost.infracost.runner import InfracostRunner  # noqa: E402
from finops.errors import FinOpsError  # noqa: E402

PLANS_DIR = REPO_ROOT / "examples" / "plans"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "infracost"

CLOUDS = ("aws", "azure", "gcp")
SCENARIOS = ("baseline", "pass", "fail")


def main() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    runner = InfracostRunner()

    try:
        runner.preflight()
    except FinOpsError as exc:
        print(f"[{exc.category.value}] {exc.message}")
        print(f"  {exc.detail}")
        return 2

    version = runner.version()
    print(f"Infracost {version.raw} (command style: {runner.command_style()})\n")

    failures: list[str] = []
    for cloud in CLOUDS:
        for scenario in SCENARIOS:
            plan = PLANS_DIR / f"{cloud}-{scenario}.json"
            if not plan.is_file():
                print(f"  {cloud}-{scenario}: skipped (no plan JSON)")
                continue
            try:
                document = runner.scan_plan(plan)
            except FinOpsError as exc:
                print(f"  {cloud}-{scenario}: FAILED - {exc.message}")
                failures.append(f"{cloud}-{scenario}")
                continue

            target = FIXTURES_DIR / f"{cloud}-{scenario}.json"
            target.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
            total = (document.get("summary") or {}).get("total_monthly_cost")
            print(f"  {cloud}-{scenario:9s} -> {target.name}  total_monthly_cost={total}")

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1

    manifest = {
        "captured_with": f"infracost {version.raw}",
        "command_style": runner.command_style(),
        "note": "Golden fixtures from real Infracost runs. Regenerate with scripts/capture_fixtures.py",
    }
    (FIXTURES_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Fixtures written to {FIXTURES_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
