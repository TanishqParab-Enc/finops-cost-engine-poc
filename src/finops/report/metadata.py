"""Deterministic resource configuration extracted from Terraform plan data.

Terraform answers "what is being created or changed"; Infracost answers "what
does that cost". This module owns the first question for every cloud, so the
report never infers configuration from price, resource names, or AI output.

The extraction is declarative: a cloud adapter maps a Terraform resource type
to an ordered tuple of FieldSpec, and the common engine resolves them. Adding a
resource type is a mapping plus a test - never a change to the report engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Rendered when a resource type is recognised but the plan omits the value.
UNAVAILABLE = "Not available in Terraform plan"


@dataclass(frozen=True)
class FieldSpec:
    """One normalized configuration fact.

    `keys` are candidate plan paths in priority order, so a provider that
    renamed an attribute across versions still resolves. Dotted segments walk
    nested blocks; a numeric segment indexes a list.
    """

    label: str
    keys: tuple[str, ...]
    formatter: Callable[[Any], str] | None = None


def _dig(values: Any, path: str) -> Any:
    """Resolve a dotted path, treating numeric segments as list indices."""
    current = values
    for segment in path.split("."):
        if current is None:
            return None
        if segment.isdigit():
            if not isinstance(current, (list, tuple)):
                return None
            index = int(segment)
            if index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple, dict)) and not value:
        return True
    return False


# -- formatters -------------------------------------------------------------
# Each renders a plan value as a short human string. They never compute or
# infer a value that the plan did not contain.


def plain(value: Any) -> str:
    return str(value)


def gigabytes(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{int(size)} GB" if size.is_integer() else f"{size} GB"


def boolean(value: Any) -> str:
    return "yes" if value else "no"


def csv(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value)


def count(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return str(len(value))
    return str(value)


def resolve(values: dict[str, Any], spec: FieldSpec) -> str | None:
    """The first non-empty candidate, formatted. None when nothing resolved."""
    if not isinstance(values, dict):
        return None
    for key in spec.keys:
        found = _dig(values, key)
        if _is_empty(found):
            continue
        formatter = spec.formatter or plain
        try:
            return formatter(found)
        except Exception:  # noqa: BLE001 - a bad value must not break the report
            return str(found)
    return None


def extract_with(
    specs: tuple[FieldSpec, ...],
    values: dict[str, Any],
    include_unavailable: bool = False,
) -> dict[str, str]:
    """Apply a mapping to plan values.

    By default an unresolved field is omitted rather than rendered as
    "unavailable", so a report only claims what the plan actually contained.
    """
    configuration: dict[str, str] = {}
    for spec in specs:
        rendered = resolve(values, spec)
        if rendered is not None:
            configuration[spec.label] = rendered
        elif include_unavailable:
            configuration[spec.label] = UNAVAILABLE
    return configuration


def configuration_delta(
    before: dict[str, str],
    after: dict[str, str],
) -> dict[str, tuple[str | None, str | None]]:
    """Fields whose value actually moved, as (before, after).

    A field present on only one side is still a change - that is how a disk
    being added or a tier being removed shows up.
    """
    delta: dict[str, tuple[str | None, str | None]] = {}
    for label in list(before) + [k for k in after if k not in before]:
        old = before.get(label)
        new = after.get(label)
        if old != new:
            delta[label] = (old, new)
    return delta
