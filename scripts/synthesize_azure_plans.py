"""Synthesize Azure Terraform plan JSON when Azure credentials are unavailable.

The azurerm provider authenticates against Entra ID when it is configured, so
unlike the AWS and Google providers it cannot produce a plan offline. This
script emits plan JSON in Terraform's documented `terraform show -json` format
(https://developer.hashicorp.com/terraform/internals/json-format) using the same
scenario values as terraform/azure/scenarios/*.tfvars.

With real Azure credentials, prefer the real thing:
    python scripts/generate_plans.py --cloud azure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "examples" / "plans"

PROVIDER = "registry.terraform.io/hashicorp/azurerm"
LOCATION = "eastus"
RESOURCE_GROUP = "finops-poc-rg"
TAGS = {"Environment": "Dev", "Service": "finops-poc"}

SCENARIOS: dict[str, dict[str, Any]] = {
    "baseline": {
        "vm_size": "Standard_B1s",
        "instance_count": 1,
        "os_disk_type": "StandardSSD_LRS",
        "os_disk_size_gb": 32,
        "data_disk_count": 0,
        "data_disk_size_gb": 512,
        "data_disk_type": "Premium_LRS",
        "enable_public_ip": False,
    },
    "pass": {
        "vm_size": "Standard_D2s_v5",
        "instance_count": 1,
        "os_disk_type": "StandardSSD_LRS",
        "os_disk_size_gb": 64,
        "data_disk_count": 0,
        "data_disk_size_gb": 512,
        "data_disk_type": "Premium_LRS",
        "enable_public_ip": False,
    },
    "fail": {
        "vm_size": "Standard_D8s_v5",
        "instance_count": 2,
        "os_disk_type": "Premium_LRS",
        "os_disk_size_gb": 128,
        "data_disk_count": 2,
        "data_disk_size_gb": 1024,
        "data_disk_type": "Premium_LRS",
        "enable_public_ip": True,
    },
}


def _vm(index: int, cfg: dict, indexed: bool) -> tuple[str, dict]:
    address = f"azurerm_linux_virtual_machine.app[{index}]" if indexed else "azurerm_linux_virtual_machine.app"
    values = {
        "name": f"finops-poc-vm-{index}",
        "resource_group_name": RESOURCE_GROUP,
        "location": LOCATION,
        "size": cfg["vm_size"],
        "admin_username": "azureuser",
        "disable_password_authentication": True,
        "os_disk": [
            {
                "caching": "ReadWrite",
                "storage_account_type": cfg["os_disk_type"],
                "disk_size_gb": cfg["os_disk_size_gb"],
            }
        ],
        "source_image_reference": [
            {
                "publisher": "Canonical",
                "offer": "0001-com-ubuntu-server-jammy",
                "sku": "22_04-lts-gen2",
                "version": "latest",
            }
        ],
        "tags": dict(TAGS),
    }
    return address, values


def _disk(index: int, cfg: dict) -> tuple[str, dict]:
    return (
        f"azurerm_managed_disk.data[{index}]",
        {
            "name": f"finops-poc-data-{index}",
            "resource_group_name": RESOURCE_GROUP,
            "location": LOCATION,
            "storage_account_type": cfg["data_disk_type"],
            "disk_size_gb": cfg["data_disk_size_gb"],
            "create_option": "Empty",
            "tags": dict(TAGS),
        },
    )


def _public_ip() -> tuple[str, dict]:
    return (
        "azurerm_public_ip.egress[0]",
        {
            "name": "finops-poc-pip",
            "resource_group_name": RESOURCE_GROUP,
            "location": LOCATION,
            "allocation_method": "Static",
            "sku": "Standard",
            "sku_tier": "Regional",
            "tags": dict(TAGS),
        },
    )


def build_plan(cfg: dict) -> dict:
    entries: list[tuple[str, str, str, int | None, dict]] = []
    indexed = True

    for i in range(cfg["instance_count"]):
        address, values = _vm(i, cfg, indexed)
        entries.append((address, "azurerm_linux_virtual_machine", "app", i, values))

    for i in range(cfg["data_disk_count"]):
        address, values = _disk(i, cfg)
        entries.append((address, "azurerm_managed_disk", "data", i, values))

    if cfg["enable_public_ip"]:
        address, values = _public_ip()
        entries.append((address, "azurerm_public_ip", "egress", 0, values))

    planned_resources = [
        {
            "address": address,
            "mode": "managed",
            "type": rtype,
            "name": name,
            "index": index,
            "provider_name": PROVIDER,
            "schema_version": 0,
            "values": values,
            "sensitive_values": {},
        }
        for address, rtype, name, index, values in entries
    ]

    resource_changes = [
        {
            "address": address,
            "mode": "managed",
            "type": rtype,
            "name": name,
            "index": index,
            "provider_name": PROVIDER,
            "change": {
                "actions": ["create"],
                "before": None,
                "after": values,
                "after_unknown": {"id": True},
                "before_sensitive": False,
                "after_sensitive": {},
            },
        }
        for address, rtype, name, index, values in entries
    ]

    config_resources = [
        {
            "address": f"{rtype}.{name}",
            "mode": "managed",
            "type": rtype,
            "name": name,
            "provider_config_key": "azurerm",
            "expressions": {},
        }
        for rtype, name in dict.fromkeys((e[1], e[2]) for e in entries)
    ]

    return {
        "format_version": "1.2",
        "terraform_version": "1.11.0",
        "planned_values": {"root_module": {"resources": planned_resources}},
        "resource_changes": resource_changes,
        "configuration": {
            "provider_config": {
                "azurerm": {
                    "name": "azurerm",
                    "full_name": PROVIDER,
                    "expressions": {},
                }
            },
            "root_module": {"resources": config_resources},
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for scenario, cfg in SCENARIOS.items():
        target = OUT_DIR / f"azure-{scenario}.json"
        target.write_text(json.dumps(build_plan(cfg), indent=2), encoding="utf-8")
        size_kb = target.stat().st_size / 1024
        print(f"  {scenario:9s} -> {target.relative_to(REPO_ROOT)} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
