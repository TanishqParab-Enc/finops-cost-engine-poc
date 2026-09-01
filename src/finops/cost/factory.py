"""Estimator selection."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..errors import ConfigurationError
from .base import CostEstimator
from .fixture_estimator import InfracostFixtureEstimator
from .infracost.estimator import InfracostEstimator
from .infracost.runner import InfracostRunner
from .mock_estimator import MockEstimator


def build_estimator(
    config: Config,
    artifact_dir: Path | None = None,
    proposed_fixture: Path | None = None,
    baseline_fixture: Path | None = None,
) -> CostEstimator:
    selected = config.cost_estimation.estimator

    if selected == "infracost":
        settings = config.cost_estimation.infracost
        runner = InfracostRunner(
            binary=settings.binary,
            command_style=settings.command_style,
            timeout_seconds=config.cost_estimation.timeout_seconds,
            config_file=settings.config_file,
            usage_file=settings.usage_file,
        )
        return InfracostEstimator(runner, artifact_dir=artifact_dir)

    if selected == "infracost_fixture":
        if proposed_fixture is None:
            raise ConfigurationError(
                "estimator 'infracost_fixture' requires --infracost-json",
                detail="Pass a recorded Infracost JSON file.",
            )
        return InfracostFixtureEstimator(proposed_fixture, baseline_fixture)

    if selected == "mock":
        return MockEstimator()

    raise ConfigurationError(f"Unknown estimator '{selected}'")
