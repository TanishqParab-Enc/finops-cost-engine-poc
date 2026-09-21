"""Trusted stack registry for the central FinOps pipeline.

A "stack" is one Terraform root the gate can price. The registry is repository
data, never a workflow input: a pull request can change the file, but the
trusted main run re-reads it from trusted code before deployment, exactly as it
re-runs the gate itself.

``deployable`` is the authorisation boundary. A non-deployable stack is priced
and reported like any other, but must never mint a cost lock and can never be
applied.

Multi-cloud (2026-09-18): every cloud stores Terraform state in the SAME S3
bucket; only the key prefix differs. Azure/GCP therefore carry cloud-scoped
identifiers (subscription/project) as registry metadata. Credentials are never
stored here - only non-secret identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError

DEFAULT_STACKS_PATH = Path("config/finops-stacks.yml")
SCHEMA_VERSION = "1.0"

SUPPORTED_CLOUDS = ("aws", "azure", "gcp")

# Fields a cloud must supply beyond the common required set. AWS is
# deliberately empty: its existing entries predate multi-cloud and must keep
# validating byte-identically.
_CLOUD_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "aws": (),
    "azure": ("subscription_id", "location", "resource_group", "name_prefix"),
    "gcp": ("project_id", "region"),
}

# Azure/GCP state keys are machine-generated and must be provably isolated per
# cloud/environment/workload. AWS keys predate this convention (e.g.
# finops-poc/dev/web-platform/terraform.tfstate has no cloud segment) and are
# intentionally exempt so existing entries keep working unchanged.
_MULTICLOUD_STATE_KEY_RE = re.compile(
    r"^finops-poc/(?P<environment>[a-z0-9-]+)/(?P<cloud>azure|gcp)/(?P<workload>[a-z0-9-]+)/terraform\.tfstate$"
)


@dataclass(frozen=True)
class Stack:
    name: str
    terraform_dir: str
    cloud: str
    deployable: bool
    environment: str
    state_key: str
    paths: tuple[str, ...]
    var_file: str | None = None
    usage_file: str | None = None
    deferred_reason: str | None = None
    # Cloud-scoped, non-secret identifiers. None for clouds that do not use them.
    subscription_id: str | None = None
    location: str | None = None
    project_id: str | None = None
    region: str | None = None
    zone: str | None = None
    # Pre-existing container the workload deploys into but does not own.
    resource_group: str | None = None
    # Isolated prefix the workload owns; bounds destroy verification.
    name_prefix: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "terraform_dir": self.terraform_dir,
            "cloud": self.cloud,
            "deployable": self.deployable,
            "environment": self.environment,
            "state_key": self.state_key,
            "var_file": self.var_file,
            "usage_file": self.usage_file,
            "paths": list(self.paths),
            "deferred_reason": self.deferred_reason,
            "subscription_id": self.subscription_id,
            "location": self.location,
            "project_id": self.project_id,
            "region": self.region,
            "zone": self.zone,
            "resource_group": self.resource_group,
            "name_prefix": self.name_prefix,
        }


def expected_state_key(cloud: str, environment: str, workload: str) -> str:
    """The one canonical state key for a non-AWS workload.

    Deterministic so a workflow can never hand-build a key that drifts from the
    one the gate baselined against.
    """
    return f"finops-poc/{environment}/{cloud}/{workload}/terraform.tfstate"


def _require(raw: dict, key: str, name: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise ConfigurationError(f"Stack {name!r} is missing required field {key!r}")
    return raw[key]


def _validate_cloud(cloud: str, name: str) -> str:
    if cloud not in SUPPORTED_CLOUDS:
        raise ConfigurationError(
            f"Stack {name!r} declares unsupported cloud {cloud!r}",
            detail="Supported clouds: " + ", ".join(SUPPORTED_CLOUDS),
        )
    return cloud


def _validate_state_key(cloud: str, environment: str, state_key: str, name: str) -> None:
    """Azure/GCP keys must be cloud- and environment-isolated.

    This is what stops an Azure run initialising against an AWS workload's
    state object, which would corrupt a validated AWS deployment.
    """
    if cloud == "aws":
        return

    match = _MULTICLOUD_STATE_KEY_RE.match(state_key)
    if not match:
        raise ConfigurationError(
            f"Stack {name!r} ({cloud}) has a non-conforming state_key",
            detail=(
                f"Expected finops-poc/<environment>/{cloud}/<workload>/terraform.tfstate, "
                f"got {state_key!r}"
            ),
        )
    if match.group("cloud") != cloud:
        raise ConfigurationError(
            f"Stack {name!r} declares cloud {cloud!r} but its state_key targets "
            f"{match.group('cloud')!r}",
            detail=state_key,
        )
    if match.group("environment") != environment:
        raise ConfigurationError(
            f"Stack {name!r} is registered for environment {environment!r} but its "
            f"state_key targets {match.group('environment')!r}",
            detail=state_key,
        )



def load_stacks(path: str | Path | None = None) -> dict[str, Stack]:
    import yaml

    stacks_path = Path(path or DEFAULT_STACKS_PATH)
    if not stacks_path.is_file():
        raise ConfigurationError(
            f"Stack registry not found: {stacks_path}",
            detail="Create config/finops-stacks.yml.",
        )
    try:
        raw = yaml.safe_load(stacks_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{stacks_path} is not valid YAML", detail=str(exc)) from exc

    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ConfigurationError(
            f"Unexpected stack registry schema_version {raw.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION})"
        )

    entries = raw.get("stacks") or {}
    if not isinstance(entries, dict) or not entries:
        raise ConfigurationError(f"{stacks_path} defines no stacks")

    stacks: dict[str, Stack] = {}
    for name, body in entries.items():
        if not isinstance(body, dict):
            raise ConfigurationError(f"Stack {name!r} must be a mapping")
        terraform_dir = str(_require(body, "terraform_dir", name)).rstrip("/")
        if terraform_dir.startswith("/") or ".." in Path(terraform_dir).parts:
            raise ConfigurationError(
                f"Stack {name!r} terraform_dir must be a relative path inside the repository",
                detail=terraform_dir,
            )
        paths = tuple(str(p) for p in (body.get("paths") or [f"{terraform_dir}/"]))
        cloud = _validate_cloud(str(_require(body, "cloud", name)), name)
        environment = str(_require(body, "environment", name))
        state_key = str(_require(body, "state_key", name))

        _validate_state_key(cloud, environment, state_key, name)

        for field in _CLOUD_REQUIRED_FIELDS[cloud]:
            _require(body, field, name)

        stacks[name] = Stack(
            name=name,
            terraform_dir=terraform_dir,
            cloud=cloud,
            deployable=bool(body.get("deployable", False)),
            environment=environment,
            state_key=state_key,
            paths=paths,
            var_file=body.get("var_file") or None,
            usage_file=body.get("usage_file") or None,
            deferred_reason=(body.get("deferred_reason") or None),
            subscription_id=(body.get("subscription_id") or None),
            location=(body.get("location") or None),
            project_id=(body.get("project_id") or None),
            region=(body.get("region") or None),
            zone=(body.get("zone") or None),
            resource_group=(body.get("resource_group") or None),
            name_prefix=(body.get("name_prefix") or None),
        )

    keys = [s.state_key for s in stacks.values()]
    if len(set(keys)) != len(keys):
        raise ConfigurationError(
            "Two stacks share a Terraform state key; stacks must be state-isolated",
            detail=", ".join(sorted(keys)),
        )
    return stacks


def get_stack(name: str, path: str | Path | None = None) -> Stack:
    stacks = load_stacks(path)
    if name not in stacks:
        raise ConfigurationError(
            f"Unknown stack {name!r}",
            detail="Known stacks: " + ", ".join(sorted(stacks)),
        )
    return stacks[name]


def validate_selection(
    stack: Stack,
    cloud: str,
    environment: str,
    require_deployable: bool = False,
) -> Stack:
    """Fail closed when an operator's selection disagrees with the registry.

    The operator supplies cloud/environment; the registry is the truth. This
    must run BEFORE any credential exchange or Terraform command, so a run
    dispatched as `cloud=aws` can never execute against an Azure stack (or
    vice versa) and reach the wrong cloud's credentials or state key.
    """
    if stack.cloud != cloud:
        raise ConfigurationError(
            f"Cloud mismatch for stack {stack.name!r}",
            detail=f"registry declares cloud={stack.cloud!r}, selection requested {cloud!r}",
        )
    if stack.environment != environment:
        raise ConfigurationError(
            f"Environment mismatch for stack {stack.name!r}",
            detail=(
                f"registry declares environment={stack.environment!r}, "
                f"selection requested {environment!r}"
            ),
        )
    if require_deployable and not stack.deployable:
        raise ConfigurationError(
            f"Stack {stack.name!r} is not deployable",
            detail="The registry marks this stack deployable: false; refusing to apply or destroy it.",
        )
    return stack



def select_stacks(changed_files: list[str], path: str | Path | None = None) -> list[Stack]:
    """Stacks whose paths a change touches. Longest prefix wins, so a nested
    workload is never attributed to the stack it happens to sit under."""
    stacks = load_stacks(path)
    ordered = sorted(
        ((prefix, stack) for stack in stacks.values() for prefix in stack.paths),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    selected: dict[str, Stack] = {}
    for changed in changed_files:
        normalised = str(changed).replace("\\", "/").lstrip("./")
        for prefix, stack in ordered:
            if normalised.startswith(prefix):
                selected[stack.name] = stack
                break
    return [selected[name] for name in sorted(selected)]
