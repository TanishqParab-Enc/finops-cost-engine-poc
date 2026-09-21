"""Cloud adapters: the only place provider-specific interpretation lives.

Each adapter supplies a resource-type to service map and a resource-type to
configuration-field map. The common report engine resolves them identically
for every cloud, so adding a cloud is a new module here, not a report change.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...models import Cloud
from ..metadata import FieldSpec, extract_with
from . import aws, azure, gcp


@dataclass(frozen=True)
class CloudAdapter:
    cloud: Cloud
    service_prefixes: tuple[tuple[str, str], ...]
    fields: dict[str, tuple[FieldSpec, ...]]
    fallback: tuple[FieldSpec, ...]

    def service_of(self, resource_type: str) -> str | None:
        lowered = (resource_type or "").lower()
        for prefix, service in self.service_prefixes:
            if lowered.startswith(prefix):
                return service
        return None

    def specs_for(self, resource_type: str) -> tuple[FieldSpec, ...]:
        return self.fields.get((resource_type or "").lower(), self.fallback)


ADAPTERS: dict[Cloud, CloudAdapter] = {
    Cloud.AWS: CloudAdapter(Cloud.AWS, aws.SERVICE_PREFIXES, aws.FIELDS, aws.FALLBACK),
    Cloud.AZURE: CloudAdapter(Cloud.AZURE, azure.SERVICE_PREFIXES, azure.FIELDS, azure.FALLBACK),
    Cloud.GCP: CloudAdapter(Cloud.GCP, gcp.SERVICE_PREFIXES, gcp.FIELDS, gcp.FALLBACK),
}

# Resource-type prefix -> cloud, so a resource can be routed without the
# caller already knowing its cloud.
_PREFIX_CLOUDS: tuple[tuple[str, Cloud], ...] = (
    ("aws_", Cloud.AWS),
    ("awscc_", Cloud.AWS),
    ("azurerm_", Cloud.AZURE),
    ("azuread_", Cloud.AZURE),
    ("azapi_", Cloud.AZURE),
    ("google_", Cloud.GCP),
)


def adapter_for(resource_type: str, cloud: Cloud | None = None) -> CloudAdapter | None:
    if cloud is not None and cloud in ADAPTERS:
        return ADAPTERS[cloud]
    lowered = (resource_type or "").lower()
    for prefix, candidate in _PREFIX_CLOUDS:
        if lowered.startswith(prefix):
            return ADAPTERS[candidate]
    return None


def service_of(resource_type: str, cloud: Cloud | None = None) -> str:
    """The service a FinOps reviewer thinks in.

    Falls back to the Terraform type rather than a guessed label, so an
    unmapped resource is obvious instead of silently mis-grouped.
    """
    adapter = adapter_for(resource_type, cloud)
    if adapter is not None:
        service = adapter.service_of(resource_type)
        if service:
            return service
    return resource_type or "unknown"


def extract_configuration(
    resource_type: str,
    values: dict | None,
    cloud: Cloud | None = None,
) -> dict[str, str]:
    """Deterministic configuration for one resource, straight from the plan.

    An unknown resource type yields an empty mapping rather than raising, so
    reporting never depends on a type having been mapped in advance.
    """
    adapter = adapter_for(resource_type, cloud)
    if adapter is None or not isinstance(values, dict):
        return {}
    return extract_with(adapter.specs_for(resource_type), values)


__all__ = [
    "ADAPTERS",
    "CloudAdapter",
    "adapter_for",
    "extract_configuration",
    "service_of",
]
