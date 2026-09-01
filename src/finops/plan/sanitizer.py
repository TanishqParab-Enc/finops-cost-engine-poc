"""Strip sensitive data before anything crosses the AI trust boundary.

Requirement section 11: only the attributes needed for resource identification,
configuration analysis and cost reasoning may leave the pipeline.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import NormalizedPlan, ResourceChange

REDACTED = "[REDACTED]"

# Attribute names that must never be forwarded, matched case-insensitively.
_SENSITIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"password",
        r"secret",
        r"token",
        r"credential",
        r"private_key",
        r"public_key",
        r"certificate",
        r"cert_body",
        r"api_key",
        r"access_key",
        r"session_key",
        r"connection_string",
        r"sas_",
        r"salt",
        r"passphrase",
        r"user_data",
        r"custom_data",
        r"kms_key",
        r"encryption_key",
        r"auth",
    )
]

# Attributes that materially affect price and are safe to share.
_COST_RELEVANT_KEYS = {
    "instance_type",
    "instance_class",
    "machine_type",
    "size",
    "sku",
    "sku_name",
    "sku_tier",
    "tier",
    "vm_size",
    "volume_type",
    "volume_size",
    "disk_size",
    "disk_size_gb",
    "disk_type",
    "storage_type",
    "allocated_storage",
    "engine",
    "engine_version",
    "multi_az",
    "replication_type",
    "account_replication_type",
    "count",
    "desired_capacity",
    "min_size",
    "max_size",
    "node_count",
    "initial_node_count",
    "capacity",
    "region",
    "location",
    "zone",
    "availability_zone",
    "os_type",
    "operating_system",
    "platform",
    "tenancy",
    "provisioned_throughput",
    "iops",
    "throughput",
    "root_block_device",
    "ebs_block_device",
    "os_disk",
    "boot_disk",
    "scratch_disk",
    "attached_disk",
    "network_interface",
    "enabled",
    "purchase_option",
    "spot_price",
    "billing_mode",
    "capacity_type",
}

_MAX_DEPTH = 4
_MAX_LIST_ITEMS = 5
_MAX_STRING_LEN = 200


def _is_sensitive(key: str) -> bool:
    return any(pattern.search(key) for pattern in _SENSITIVE_PATTERNS)


def _sanitize_value(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {k: (REDACTED if _is_sensitive(k) else _sanitize_value(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v, depth + 1) for v in value[:_MAX_LIST_ITEMS]]
    if isinstance(value, str):
        return value[:_MAX_STRING_LEN]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STRING_LEN]


def sanitize_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Allowlist cost-relevant attributes, then redact anything sensitive."""
    if not isinstance(attributes, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in attributes.items():
        if key not in _COST_RELEVANT_KEYS:
            continue
        result[key] = REDACTED if _is_sensitive(key) else _sanitize_value(value, 1)
    return result


def sanitize_change(change: ResourceChange) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "address": change.address,
        "cloud": change.cloud.value,
        "resource_type": change.resource_type,
        "action": change.action.value,
        "region": change.region,
    }
    before = sanitize_attributes(change.before)
    after = sanitize_attributes(change.after)
    if before:
        payload["before"] = before
    if after:
        payload["after"] = after
    return payload


def sanitize_plan(plan: NormalizedPlan, max_resources: int = 40) -> dict[str, Any]:
    relevant = plan.cost_relevant_changes
    return {
        "terraform_version": plan.terraform_version,
        "clouds": [c.value for c in plan.clouds],
        "total_changes": len(relevant),
        "truncated": len(relevant) > max_resources,
        "changes": [sanitize_change(c) for c in relevant[:max_resources]],
    }
