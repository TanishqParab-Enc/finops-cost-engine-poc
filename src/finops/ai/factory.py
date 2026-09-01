"""AI provider selection and the non-blocking analysis wrapper."""

from __future__ import annotations

from ..config import AIConfig
from ..errors import AIError
from ..models import AIAnalysis, CostEstimate, NormalizedPlan, PolicyDecision, as_float
from .base import AIProvider
from .mock_provider import MockAIProvider


def build_provider(config: AIConfig) -> AIProvider:
    if config.provider == "mock":
        return MockAIProvider()
    if config.provider == "azure_openai":
        from .providers import AzureOpenAIProvider

        return AzureOpenAIProvider(timeout_seconds=config.timeout_seconds)
    if config.provider == "openai":
        from .providers import OpenAIProvider

        return OpenAIProvider(timeout_seconds=config.timeout_seconds)
    if config.provider == "bedrock":
        from .bedrock_provider import BedrockProvider

        return BedrockProvider(timeout_seconds=config.timeout_seconds)
    raise AIError(f"Unknown AI provider '{config.provider}'")


def unavailable(decision: PolicyDecision, estimate: CostEstimate, error: str) -> AIAnalysis:
    return AIAnalysis(
        summary="AI explanation unavailable. The deterministic cost result below is unaffected.",
        cost_impact=as_float(decision.observed_value) or 0.0,
        currency=estimate.currency,
        threshold=as_float(decision.threshold_value) or 0.0,
        decision="BLOCK" if decision.status.value == "FAIL" else "ALLOW",
        reason="; ".join(decision.reasons) or "See policy decision.",
        cost_drivers=[
            f"{r.address}: {as_float(r.delta_monthly_cost)}/month"
            for r in estimate.top_cost_drivers(3)
        ],
        recommendation="",
        provider="none",
        available=False,
        error=error,
    )


def analyze(
    plan: NormalizedPlan,
    estimate: CostEstimate,
    decision: PolicyDecision,
    config: AIConfig,
) -> tuple[AIAnalysis, AIError | None]:
    """Never raises. AI is explanatory, so its failure cannot change the gate."""
    if not config.enabled:
        return unavailable(decision, estimate, "AI analysis disabled by configuration"), None
    try:
        provider = build_provider(config)
        return provider.analyze(plan, estimate, decision, config.max_resources_in_prompt), None
    except AIError as exc:
        return unavailable(decision, estimate, exc.message), exc
    except Exception as exc:  # noqa: BLE001 - a broken provider must not break the gate
        error = AIError("Unexpected AI provider failure", detail=str(exc))
        return unavailable(decision, estimate, error.message), error
