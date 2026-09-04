"""Trusted stack registry for the central FinOps pipeline.

A "stack" is one Terraform root the gate can price. The registry is repository
data, never a workflow input: a pull request can change the file, but the
trusted main run re-reads it from trusted code before deployment, exactly as it
re-runs the gate itself.

``deployable`` is the authorisation boundary. A non-deployable stack is priced
and reported like any other, but must never mint a cost lock and can never be
applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError

DEFAULT_STACKS_PATH = Path("config/finops-stacks.yml")
SCHEMA_VERSION = "1.0"


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
    deferred_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "terraform_dir": self.terraform_dir,
            "cloud": self.cloud,
            "deployable": self.deployable,
            "environment": self.environment,
            "state_key": self.state_key,
            "var_file": self.var_file,
            "paths": list(self.paths),
            "deferred_reason": self.deferred_reason,
        }


def _require(raw: dict, key: str, name: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise ConfigurationError(f"Stack {name!r} is missing required field {key!r}")
    return raw[key]


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
        stacks[name] = Stack(
            name=name,
            terraform_dir=terraform_dir,
            cloud=str(_require(body, "cloud", name)),
            deployable=bool(body.get("deployable", False)),
            environment=str(_require(body, "environment", name)),
            state_key=str(_require(body, "state_key", name)),
            paths=paths,
            var_file=body.get("var_file") or None,
            deferred_reason=(body.get("deferred_reason") or None),
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
