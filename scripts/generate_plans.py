"""Generate Terraform plan JSON files for every POC scenario.

For each cloud and scenario:
    terraform init
    terraform plan -out tfplan.binary -var-file scenarios/<scenario>.tfvars
    terraform show -json tfplan.binary > examples/plans/<cloud>-<scenario>.json

The POC provider blocks use mock credentials with validation skipped, so this
runs offline. A real pipeline authenticates with OIDC and plans against real
state.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDS = ("aws", "azure", "gcp")
SCENARIOS = ("baseline", "pass", "fail")


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def terraform_init(cloud_dir: Path) -> bool:
    print(f"  init ... ", end="", flush=True)
    proc = run(["terraform", "init", "-input=false", "-no-color"], cloud_dir)
    if proc.returncode != 0:
        print("FAILED")
        print(_tail(proc.stderr or proc.stdout))
        return False
    print("ok")
    return True


def generate(cloud: str, scenario: str, out_dir: Path) -> bool:
    cloud_dir = REPO_ROOT / "terraform" / cloud
    var_file = cloud_dir / "scenarios" / f"{scenario}.tfvars"
    if not var_file.is_file():
        print(f"  {scenario:9s} skipped (no {var_file.name})")
        return True

    plan_binary = cloud_dir / "tfplan.binary"
    proc = run(
        [
            "terraform",
            "plan",
            "-input=false",
            "-no-color",
            "-refresh=false",
            f"-var-file=scenarios/{scenario}.tfvars",
            "-out=tfplan.binary",
        ],
        cloud_dir,
    )
    if proc.returncode != 0:
        print(f"  {scenario:9s} PLAN FAILED")
        print(_tail(proc.stderr or proc.stdout))
        return False

    show = run(["terraform", "show", "-json", "tfplan.binary"], cloud_dir)
    plan_binary.unlink(missing_ok=True)
    if show.returncode != 0:
        print(f"  {scenario:9s} SHOW FAILED")
        print(_tail(show.stderr or show.stdout))
        return False

    target = out_dir / f"{cloud}-{scenario}.json"
    target.write_text(show.stdout, encoding="utf-8")
    print(f"  {scenario:9s} -> {target.relative_to(REPO_ROOT)} ({len(show.stdout) / 1024:.1f} KB)")
    return True


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(f"      {line}" for line in (text or "").strip().splitlines()[-lines:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", choices=(*CLOUDS, "all"), default="all")
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    args = parser.parse_args()

    clouds = CLOUDS if args.cloud == "all" else (args.cloud,)
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)

    out_dir = REPO_ROOT / "examples" / "plans"
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    for cloud in clouds:
        cloud_dir = REPO_ROOT / "terraform" / cloud
        if not cloud_dir.is_dir():
            print(f"{cloud}: skipped (no terraform/{cloud})")
            continue
        print(f"{cloud}:")
        if not terraform_init(cloud_dir):
            failures.append(f"{cloud}/init")
            continue
        for scenario in scenarios:
            if not generate(cloud, scenario, out_dir):
                failures.append(f"{cloud}/{scenario}")

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print(f"All plan JSON files written to {out_dir.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
