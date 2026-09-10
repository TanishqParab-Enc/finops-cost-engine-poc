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
    # Optional machine-readable sub-code, narrower than `category`.
    code: str | None = None

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        payload = {
            "category": self.category.value,
            "message": self.message,
            "detail": self.detail,
        }
        if self.code is not None:
            payload["code"] = self.code
        return payload


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


class BaselineUnavailableError(CostEstimationError):
    """The deployed baseline could not be established, so no trustworthy
    incremental cost exists.

    Distinct from a genuinely greenfield stack: an accessible remote backend
    holding no state yields a real, empty baseline (cost $0). This error only
    covers the case where the expected remote backend/state could not be
    accessed or validated at all - which must fail closed rather than be
    silently priced as if nothing were deployed.
    """

    code = "BASELINE_UNAVAILABLE"


class PolicyError(FinOpsError):
    category = FailureCategory.POLICY


class AIError(FinOpsError):
    """AI provider unavailable or returned a malformed/unschematic result."""

    category = FailureCategory.AI
