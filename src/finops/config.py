"""Configuration loading.

Precedence: environment variable > YAML file > built-in default.
The threshold lives only in YAML/env so the business rule can change without
touching engine code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError

DEFAULT_CONFIG_PATH = Path("config/finops-policy.yaml")

VALID_METRICS = {
    "incremental_monthly_cost",
    "incremental_annual_cost",
    "incremental_percentage",
    "total_monthly_cost",
}

METRIC_UNITS = {
    "incremental_monthly_cost": "{currency}/month",
    "incremental_annual_cost": "{currency}/year",
    "incremental_percentage": "% of baseline",
    "total_monthly_cost": "{currency}/month",
}

VALID_FAILSAFE_ACTIONS = {"BLOCK", "WARN"}


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"'{field_name}' must be numeric, got {value!r}", detail=str(exc)
        ) from exc


@dataclass(frozen=True)
class ThresholdConfig:
    metric: str
    value: Decimal
    currency: str
    equality_is_pass: bool
    allow_cost_reductions: bool

    @property
    def unit(self) -> str:
        return METRIC_UNITS[self.metric].format(currency=self.currency)

    @property
    def comparison(self) -> str:
        return "<=" if self.equality_is_pass else "<"


@dataclass(frozen=True)
class InfracostConfig:
    binary: str = "infracost"
    command_style: str = "auto"
    config_file: str | None = None
    usage_file: str | None = None


@dataclass(frozen=True)
class CostEstimationConfig:
    estimator: str
    allow_non_authoritative_lock: bool
    timeout_seconds: int
    infracost: InfracostConfig


@dataclass(frozen=True)
class FailSafeConfig:
    on_plan_failure: str
    on_estimation_failure: str
    on_unsupported_provider: str
    on_unsupported_resource: str
    on_unknown_cost_resource: str
    on_ai_failure: str

    def blocks(self, key: str) -> bool:
        return getattr(self, key) == "BLOCK"


@dataclass(frozen=True)
class AIConfig:
    provider: str
    enabled: bool
    required: bool
    timeout_seconds: int
    max_resources_in_prompt: int


@dataclass(frozen=True)
class ChangeDetectionConfig:
    infrastructure_globs: list[str]
    ignore_globs: list[str]


@dataclass(frozen=True)
class CostLockConfig:
    output_dir: str
    bind_to_plan_fingerprint: bool


@dataclass(frozen=True)
class ExceptionConfig:
    """Audited override for an over-threshold change. Never turns FAIL into PASS."""

    enabled: bool = True
    # Empty by default: with no allowlist, every exception is rejected.
    approvers: list[str] = field(default_factory=list)
    max_ttl_days: int = 7
    max_ceiling_ratio: float = 1.1
    require_non_author_approval: bool = True
    require_review_approval: bool = True


@dataclass(frozen=True)
class Config:
    threshold: ThresholdConfig
    cost_estimation: CostEstimationConfig
    fail_safe: FailSafeConfig
    ai: AIConfig
    change_detection: ChangeDetectionConfig
    cost_lock: CostLockConfig
    exceptions: ExceptionConfig = field(default_factory=ExceptionConfig)
    source_path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path or _env("FINOPS_CONFIG") or DEFAULT_CONFIG_PATH)

    if not config_path.is_file():
        raise ConfigurationError(
            f"FinOps policy config not found: {config_path}",
            detail="Create config/finops-policy.yaml or set FINOPS_CONFIG.",
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"Could not parse {config_path}", detail=str(exc)
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(f"{config_path} must contain a YAML mapping")

    return _build(raw, str(config_path))


def _build(raw: dict[str, Any], source_path: str) -> Config:
    threshold_raw = raw.get("threshold") or {}
    evaluation_raw = raw.get("evaluation") or {}

    metric = _env("FINOPS_THRESHOLD_METRIC") or threshold_raw.get(
        "metric", "incremental_monthly_cost"
    )
    if metric not in VALID_METRICS:
        raise ConfigurationError(
            f"Unknown threshold.metric '{metric}'",
            detail=f"Valid metrics: {', '.join(sorted(VALID_METRICS))}",
        )

    raw_value = _env("FINOPS_THRESHOLD_VALUE") or threshold_raw.get("value")
    if raw_value is None:
        raise ConfigurationError("threshold.value is required")
    value = _decimal(raw_value, "threshold.value")
    if value < 0:
        raise ConfigurationError(f"threshold.value must be >= 0, got {value}")

    threshold = ThresholdConfig(
        metric=metric,
        value=value,
        currency=(_env("FINOPS_THRESHOLD_CURRENCY") or threshold_raw.get("currency", "USD")).upper(),
        equality_is_pass=bool(evaluation_raw.get("equality_is_pass", True)),
        allow_cost_reductions=bool(evaluation_raw.get("allow_cost_reductions", True)),
    )

    cost_raw = raw.get("cost_estimation") or {}
    infracost_raw = cost_raw.get("infracost") or {}
    estimator = (_env("FINOPS_COST_ESTIMATOR") or cost_raw.get("estimator", "infracost")).lower()
    if estimator not in {"infracost", "infracost_fixture", "mock"}:
        raise ConfigurationError(
            f"Unknown cost_estimation.estimator '{estimator}'",
            detail="Valid: infracost, infracost_fixture, mock",
        )

    command_style = (infracost_raw.get("command_style") or "auto").lower()
    if command_style not in {"auto", "v2", "v0.10"}:
        raise ConfigurationError(
            f"Unknown infracost.command_style '{command_style}'",
            detail="Valid: auto, v2, v0.10",
        )

    cost_estimation = CostEstimationConfig(
        estimator=estimator,
        allow_non_authoritative_lock=bool(cost_raw.get("allow_non_authoritative_lock", False)),
        timeout_seconds=int(cost_raw.get("timeout_seconds", 300)),
        infracost=InfracostConfig(
            binary=_env("INFRACOST_BINARY") or infracost_raw.get("binary") or "infracost",
            command_style=command_style,
            config_file=infracost_raw.get("config_file"),
            usage_file=infracost_raw.get("usage_file"),
        ),
    )

    fs_raw = raw.get("fail_safe") or {}
    fail_safe_values = {
        "on_plan_failure": fs_raw.get("on_plan_failure", "BLOCK"),
        "on_estimation_failure": fs_raw.get("on_estimation_failure", "BLOCK"),
        "on_unsupported_provider": fs_raw.get("on_unsupported_provider", "BLOCK"),
        "on_unsupported_resource": fs_raw.get("on_unsupported_resource", "WARN"),
        "on_unknown_cost_resource": fs_raw.get("on_unknown_cost_resource", "WARN"),
        "on_ai_failure": fs_raw.get("on_ai_failure", "WARN"),
    }
    for key, action in fail_safe_values.items():
        if action not in VALID_FAILSAFE_ACTIONS:
            raise ConfigurationError(
                f"fail_safe.{key} must be BLOCK or WARN, got {action!r}"
            )
    fail_safe = FailSafeConfig(**fail_safe_values)

    ai_raw = raw.get("ai") or {}
    ai = AIConfig(
        provider=(_env("FINOPS_AI_PROVIDER") or ai_raw.get("provider", "mock")).lower(),
        enabled=bool(ai_raw.get("enabled", True)),
        required=bool(ai_raw.get("required", False)),
        timeout_seconds=int(ai_raw.get("timeout_seconds", 30)),
        max_resources_in_prompt=int(ai_raw.get("max_resources_in_prompt", 40)),
    )

    cd_raw = raw.get("change_detection") or {}
    change_detection = ChangeDetectionConfig(
        infrastructure_globs=list(cd_raw.get("infrastructure_globs") or ["**/*.tf"]),
        ignore_globs=list(cd_raw.get("ignore_globs") or []),
    )

    lock_raw = raw.get("cost_lock") or {}
    cost_lock = CostLockConfig(
        output_dir=_env("FINOPS_OUTPUT_DIR") or lock_raw.get("output_dir", ".finops"),
        bind_to_plan_fingerprint=bool(lock_raw.get("bind_to_plan_fingerprint", True)),
    )

    exc_raw = raw.get("exceptions") or {}
    # Approvers live in CI config, not the repo, so a pull request cannot add
    # itself to the allowlist it is about to be judged by.
    approvers_env = _env("FINOPS_APPROVERS")
    approvers = (
        [a.strip() for a in approvers_env.split(",") if a.strip()]
        if approvers_env
        else [str(a).strip() for a in (exc_raw.get("approvers") or []) if str(a).strip()]
    )
    exceptions = ExceptionConfig(
        enabled=bool(exc_raw.get("enabled", True)),
        approvers=approvers,
        max_ttl_days=int(exc_raw.get("max_ttl_days", 7)),
        max_ceiling_ratio=float(exc_raw.get("max_ceiling_ratio", 1.1)),
        require_non_author_approval=bool(exc_raw.get("require_non_author_approval", True)),
        require_review_approval=bool(exc_raw.get("require_review_approval", True)),
    )

    return Config(
        threshold=threshold,
        cost_estimation=cost_estimation,
        fail_safe=fail_safe,
        ai=ai,
        change_detection=change_detection,
        cost_lock=cost_lock,
        exceptions=exceptions,
        source_path=source_path,
        raw=raw,
    )
