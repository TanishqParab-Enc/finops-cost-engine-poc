#!/usr/bin/env python3
"""Write the registry's cloud identifiers as an auto-loaded tfvars file.

Deliberately a file rather than TF_VAR_* environment variables: TF_VAR_ is
process-wide, so an empty value for one cloud (e.g. TF_VAR_region="") would
shadow a same-named variable in another cloud's stack. A file written only for
the cloud being run cannot do that, and AWS stacks never invoke this at all.

TFVARS_ROOTS lists the checkout roots that need the file - the cost gate plans
the same stack from two checkouts ("head baseline"), destroy uses one (".").
"""

from __future__ import annotations

import json
import os
import sys

FILENAME = "zz-finops-cloud.auto.tfvars.json"

REQUIRED: dict[str, dict[str, str]] = {
    "azure": {
        "subscription_id": "SUBSCRIPTION_ID",
        "resource_group_name": "RESOURCE_GROUP",
        "location": "LOCATION",
        "admin_ssh_public_key": "AZURE_SSH_PUBLIC_KEY",
    },
    "gcp": {
        "project_id": "PROJECT_ID",
        "region": "GCP_REGION",
        "zone": "GCP_ZONE",
    },
}


def build_values(cloud: str, env: dict[str, str]) -> dict[str, str]:
    if cloud not in REQUIRED:
        raise SystemExit(
            f"::error title=Unsupported cloud::{cloud!r} has no Terraform input mapping. "
            f"AWS stacks must not call this script."
        )
    values = {name: env.get(var, "") for name, var in REQUIRED[cloud].items()}
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise SystemExit(
            f"::error title=Missing registry values::{cloud} stack is missing {missing}. "
            f"Fail closed rather than planning with an undefined input."
        )
    return values


def main() -> int:
    env = os.environ
    cloud = env.get("CLOUD", "").strip().lower()
    stack_dir = env.get("STACK_DIR", "").strip()
    if not stack_dir:
        raise SystemExit("::error title=No stack directory::STACK_DIR is required.")

    values = build_values(cloud, env)
    roots = env.get("TFVARS_ROOTS", ".").split()

    for root in roots:
        path = os.path.join(root, stack_dir, FILENAME)
        if not os.path.isdir(os.path.dirname(path)):
            raise SystemExit(f"::error title=Missing stack directory::{os.path.dirname(path)}")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
        print(f"wrote {path} ({', '.join(sorted(values))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
