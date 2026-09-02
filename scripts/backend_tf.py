"""Run terraform plan for a backend layer, avoiding PowerShell native-arg mangling."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAYERS = {
    "bootstrap": REPO_ROOT / "backend" / "bootstrap",
    "dev": REPO_ROOT / "backend" / "environments" / "dev",
    "staging": REPO_ROOT / "backend" / "environments" / "staging",
    "prod": REPO_ROOT / "backend" / "environments" / "prod",
    "github": REPO_ROOT / "backend" / "github",
}


def run(argv: list[str], cwd: Path) -> int:
    print(f"$ {' '.join(argv)}   (in {cwd.relative_to(REPO_ROOT)})\n")
    proc = subprocess.run(argv, cwd=cwd, text=True, encoding="utf-8", errors="replace")
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layer", choices=sorted(LAYERS))
    parser.add_argument("--apply", action="store_true", help="Apply instead of plan")
    parser.add_argument("--backend-config", default=None)
    args = parser.parse_args()

    cwd = LAYERS[args.layer]
    tfvars = cwd / "terraform.tfvars"
    if not tfvars.is_file():
        print(f"Missing {tfvars.relative_to(REPO_ROOT)}")
        print(f"  copy it first: cp terraform.tfvars.example terraform.tfvars")
        return 2

    init = ["terraform", "init", "-input=false", "-no-color"]
    if args.backend_config:
        init.append(f"-backend-config={args.backend_config}")
    elif args.layer == "bootstrap":
        init.append("-backend=false")
    if run(init, cwd) != 0:
        return 1

    command = "apply" if args.apply else "plan"
    argv = ["terraform", command, "-input=false", "-no-color", "-var-file=terraform.tfvars"]
    if not args.apply:
        argv.append("-out=tfplan.binary")

    return run(argv, cwd)


if __name__ == "__main__":
    sys.exit(main())
