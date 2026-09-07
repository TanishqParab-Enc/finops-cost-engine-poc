"""Shared test fixtures."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from finops.config import (
    AIConfig,
    ChangeDetectionConfig,
    Config,
    CostEstimationConfig,
    CostLockConfig,
    ExceptionConfig,
    FailSafeConfig,
    InfracostConfig,
    ThresholdConfig,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = REPO_ROOT / "examples" / "plans"
INFRACOST_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "infracost"


def make_config(
    *,
    threshold: str | int | float = 100,
    metric: str = "incremental_monthly_cost",
    equality_is_pass: bool = True,
    allow_cost_reductions: bool = True,
    estimator: str = "infracost_fixture",
    allow_non_authoritative_lock: bool = False,
    output_dir: str = ".finops-test",
    on_unsupported_resource: str = "WARN",
    on_unknown_cost_resource: str = "WARN",
    ai_enabled: bool = True,
    ai_required: bool = False,
    exceptions_enabled: bool = True,
    approvers: list[str] | None = None,
    max_ttl_days: int = 7,
    max_ceiling_ratio: float = 1.1,
    require_non_author_approval: bool = True,
    require_review_approval: bool = True,
) -> Config:
    return Config(
        threshold=ThresholdConfig(
            metric=metric,
            value=Decimal(str(threshold)),
            currency="USD",
            equality_is_pass=equality_is_pass,
            allow_cost_reductions=allow_cost_reductions,
        ),
        cost_estimation=CostEstimationConfig(
            estimator=estimator,
            allow_non_authoritative_lock=allow_non_authoritative_lock,
            timeout_seconds=60,
            infracost=InfracostConfig(),
        ),
        fail_safe=FailSafeConfig(
            on_plan_failure="BLOCK",
            on_estimation_failure="BLOCK",
            on_unsupported_provider="BLOCK",
            on_unsupported_resource=on_unsupported_resource,
            on_unknown_cost_resource=on_unknown_cost_resource,
            on_ai_failure="WARN",
        ),
        ai=AIConfig(
            provider="mock",
            enabled=ai_enabled,
            required=ai_required,
            timeout_seconds=5,
            max_resources_in_prompt=40,
        ),
        change_detection=ChangeDetectionConfig(
            infrastructure_globs=["**/*.tf", "**/*.tfvars"],
            ignore_globs=["**/.terraform/**", "**/*.md"],
        ),
        cost_lock=CostLockConfig(output_dir=output_dir, bind_to_plan_fingerprint=True),
        exceptions=ExceptionConfig(
            enabled=exceptions_enabled,
            approvers=list(approvers or []),
            max_ttl_days=max_ttl_days,
            max_ceiling_ratio=max_ceiling_ratio,
            require_non_author_approval=require_non_author_approval,
            require_review_approval=require_review_approval,
        ),
        source_path="test",
    )


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return make_config(output_dir=str(tmp_path / ".finops"))


@pytest.fixture
def plans_dir() -> Path:
    return PLANS_DIR


@pytest.fixture
def infracost_fixtures() -> Path:
    return INFRACOST_FIXTURES


def load_infracost(name: str) -> dict:
    return json.loads((INFRACOST_FIXTURES / name).read_text(encoding="utf-8"))


def plan_path(name: str) -> Path:
    return PLANS_DIR / name
