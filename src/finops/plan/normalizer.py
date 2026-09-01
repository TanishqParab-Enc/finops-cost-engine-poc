"""Component C - Terraform plan JSON to a cloud-agnostic change model.

Consumes the documented `terraform show -json` format:
https://developer.hashicorp.com/terraform/internals/json-format
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import PlanError
from ..models import Action, Cloud, NormalizedPlan, ResourceChange

SUPPORTED_MAJOR_FORMAT_VERSIONS = {"0", "1"}

_PROVIDER_CLOUDS: list[tuple[tuple[str, ...], Cloud]] = [
    (("/aws", "hashicorp/aws", "aws"), Cloud.AWS),
    (("azurerm", "azuread", "azapi", "azurestack"), Cloud.AZURE),
    (("google", "google-beta"), Cloud.GCP),
]

_TYPE_PREFIX_CLOUDS: list[tuple[str, Cloud]] = [
    ("aws_", Cloud.AWS),
    ("awscc_", Cloud.AWS),
    ("azurerm_", Cloud.AZURE),
    ("azuread_", Cloud.AZURE),
    ("azapi_", Cloud.AZURE),
    ("google_", Cloud.GCP),
]


def detect_cloud(resource_type: str, provider_name: str = "") -> Cloud:
    """Resource type wins: it is unambiguous and always present."""
    lowered_type = (resource_type or "").lower()
    for prefix, cloud in _TYPE_PREFIX_CLOUDS:
        if lowered_type.startswith(prefix):
            return cloud

    provider = (provider_name or "").lower()
    short = provider.rsplit("/", 1)[-1]
    for needles, cloud in _PROVIDER_CLOUDS:
        if short in needles or any(needle in provider for needle in needles):
            return cloud

    return Cloud.UNKNOWN


def normalize_action(actions: list[str]) -> Action:
    normalized = [a.lower() for a in (actions or [])]
    if not normalized:
        return Action.NOOP
    if "delete" in normalized and "create" in normalized:
        return Action.REPLACE
    if normalized == ["create"]:
        return Action.CREATE
    if normalized == ["delete"]:
        return Action.DELETE
    if normalized == ["update"]:
        return Action.UPDATE
    if normalized == ["read"]:
        return Action.READ
    return Action.NOOP


def _provider_regions(plan: dict[str, Any]) -> dict[str, str]:
    """Region declared on each provider block, keyed by provider config key."""
    regions: dict[str, str] = {}
    provider_config = (plan.get("configuration") or {}).get("provider_config") or {}
    for key, cfg in provider_config.items():
        expressions = cfg.get("expressions") or {}
        for attr in ("region", "location"):
            constant = (expressions.get(attr) or {}).get("constant_value")
            if isinstance(constant, str) and constant:
                regions[key] = constant
                regions[cfg.get("name", key)] = constant
                break
    return regions


def _resource_region(values: dict[str, Any], cloud: Cloud, fallback: str | None) -> str | None:
    if not isinstance(values, dict):
        return fallback

    for attr in ("region", "location"):
        value = values.get(attr)
        if isinstance(value, str) and value:
            return value

    if cloud is Cloud.AWS:
        az = values.get("availability_zone")
        if isinstance(az, str) and len(az) > 1 and az[-1].isalpha():
            return az[:-1]
    if cloud is Cloud.GCP:
        zone = values.get("zone")
        if isinstance(zone, str) and zone.count("-") >= 2:
            return zone.rsplit("-", 1)[0]

    return fallback


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_plan_json(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path)
    if not plan_path.is_file():
        raise PlanError(f"Terraform plan JSON not found: {plan_path}")
    try:
        return json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(
            f"{plan_path} is not valid JSON",
            detail="Generate it with: terraform show -json tfplan.binary > plan.json",
        ) from exc


def normalize_plan(plan: dict[str, Any], source_path: str | None = None) -> NormalizedPlan:
    if not isinstance(plan, dict):
        raise PlanError("Terraform plan JSON must be an object")

    format_version = str(plan.get("format_version") or "")
    if not format_version:
        raise PlanError(
            "Missing 'format_version' - this does not look like terraform show -json output",
            detail="Generate it with: terraform show -json tfplan.binary > plan.json",
        )

    major = format_version.split(".", 1)[0]
    if major not in SUPPORTED_MAJOR_FORMAT_VERSIONS:
        raise PlanError(
            f"Unsupported Terraform plan format_version '{format_version}'",
            detail=f"Supported major versions: {sorted(SUPPORTED_MAJOR_FORMAT_VERSIONS)}",
        )

    if plan.get("errored") is True:
        raise PlanError(
            "Terraform reported the plan as errored; refusing to estimate cost",
            detail="Fix the Terraform errors and re-run the plan.",
        )

    provider_regions = _provider_regions(plan)
    changes: list[ResourceChange] = []
    clouds: set[Cloud] = set()

    for entry in plan.get("resource_changes") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("mode") != "managed":
            continue

        resource_type = entry.get("type") or ""
        provider_name = entry.get("provider_name") or ""
        cloud = detect_cloud(resource_type, provider_name)
        change = _as_dict(entry.get("change"))
        action = normalize_action(change.get("actions") or [])

        before = _as_dict(change.get("before"))
        after = _as_dict(change.get("after"))

        fallback_region = provider_regions.get(provider_name.rsplit("/", 1)[-1]) or next(
            iter(provider_regions.values()), None
        )
        region = _resource_region(after or before, cloud, fallback_region)

        resource_change = ResourceChange(
            address=entry.get("address") or "",
            resource_type=resource_type,
            name=entry.get("name") or "",
            cloud=cloud,
            action=action,
            provider_name=provider_name,
            module_address=entry.get("module_address"),
            index=entry.get("index"),
            region=region,
            before=before,
            after=after,
        )
        changes.append(resource_change)
        if resource_change.is_cost_relevant:
            clouds.add(cloud)

    return NormalizedPlan(
        terraform_version=str(plan.get("terraform_version") or ""),
        format_version=format_version,
        changes=changes,
        clouds=sorted(clouds, key=lambda c: c.value),
        source_path=source_path,
    )


def normalize_plan_file(path: str | Path) -> NormalizedPlan:
    return normalize_plan(load_plan_json(path), source_path=str(path))
