"""Run every POC scenario end to end and print a summary table.

    python scripts/demo.py                # real Infracost (needs auth)
    python scripts/demo.py --fixtures     # replay golden fixtures (offline)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

CLOUDS = ("aws", "azure", "gcp")
SCENARIOS = ("pass", "fail")

STATUS_LABEL = {0: "PASS", 1: "FAIL", 2: "ERROR"}


def run_scenario(cloud: str, scenario: str, use_fixtures: bool) -> tuple[int, str]:
    plans = REPO_ROOT / "examples" / "plans"
    argv = [
        sys.executable,
        "-m",
        "finops.cli",
        "analyze",
        "--plan",
        str(plans / f"{cloud}-{scenario}.json"),
        "--baseline-plan",
        str(plans / f"{cloud}-baseline.json"),
        "--commit",
        f"demo-{cloud}-{scenario}",
        "--execution-id",
        f"demo-{cloud}-{scenario}",
    ]

    env = None
    if use_fixtures:
        import os

        fixtures = REPO_ROOT / "tests" / "fixtures" / "infracost"
        argv += [
            "--infracost-json",
            str(fixtures / f"{cloud}-{scenario}.json"),
            "--baseline-infracost-json",
            str(fixtures / f"{cloud}-baseline.json"),
        ]
        env = {**os.environ, "FINOPS_COST_ESTIMATOR": "infracost_fixture"}

    proc = subprocess.run(
        argv, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )
    return proc.returncode, proc.stdout + proc.stderr


def parse(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.strip().startswith(key):
            return line.split(":", 1)[1].strip()
    return "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true", help="Replay golden fixtures (offline)")
    args = parser.parse_args()

    mode = "golden fixtures (offline)" if args.fixtures else "live Infracost"
    print(f"FinOps shift-left cost gate demo - {mode}\n")

    header = f"{'CLOUD':<7} {'SCENARIO':<9} {'PREVIOUS':>12} {'PROJECTED':>12} {'INCREMENTAL':>13} {'RESULT':>7} {'EXIT':>5}"
    print(header)
    print("-" * len(header))

    failures = 0
    for cloud in CLOUDS:
        for scenario in SCENARIOS:
            code, output = run_scenario(cloud, scenario, args.fixtures)
            label = STATUS_LABEL.get(code, f"?{code}")
            expected = 0 if scenario == "pass" else 1
            if code != expected:
                failures += 1
                label += "!"
            print(
                f"{cloud:<7} {scenario:<9} "
                f"{parse(output, 'previous'):>12} "
                f"{parse(output, 'projected'):>12} "
                f"{parse(output, 'incremental'):>13} "
                f"{label:>7} {code:>5}"
            )

    print()
    print("Expected: pass -> exit 0 (cost locked), fail -> exit 1 (build blocked)")
    if failures:
        print(f"\n{failures} scenario(s) did not behave as expected.")
        return 1
    print("\nAll scenarios behaved as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
