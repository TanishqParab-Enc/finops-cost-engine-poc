"""Failure taxonomy.

The requirement distinguishes four failure classes so CI/CD can react
differently to each. Every error carries a ``category`` used by the policy
engine to decide whether the pipeline is blocked.
"""

from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    INFRASTRUCTURE_VALIDATION = "INFRASTRUCTURE_VALIDATION"
    COST_ESTIMATION = "COST_ESTIMATION"
    POLICY = "POLICY"
    AI = "AI"
    CONFIGURATION = "CONFIGURATION"


class FinOpsError(Exception):
    category = FailureCategory.POLICY

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "message": self.message,
            "detail": self.detail,
        }


class ConfigurationError(FinOpsError):
    """Threshold/config file missing, unreadable or semantically invalid."""

    category = FailureCategory.CONFIGURATION


class PlanError(FinOpsError):
    """Terraform plan missing, unreadable, wrong format version or errored."""

    category = FailureCategory.INFRASTRUCTURE_VALIDATION


class CostEstimationError(FinOpsError):
    """Pricing lookup or estimator execution failed."""

    category = FailureCategory.COST_ESTIMATION


class UnsupportedProviderError(CostEstimationError):
    """Plan contains a cloud provider the engine cannot price."""


class PolicyError(FinOpsError):
    category = FailureCategory.POLICY


class AIError(FinOpsError):
    """AI provider unavailable or returned a malformed/unschematic result."""

    category = FailureCategory.AI
