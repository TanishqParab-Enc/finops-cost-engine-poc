"""Infracost CLI invocation with automatic v2 / v0.10 command-shape detection.

v2:     infracost scan <plan.json> --json
v0.10:  infracost breakdown --path <plan.json> --format json

Verified 2026-09-01 against CLI v2.16.2: `infracost scan` has no --compare-to
flag, so incremental cost is derived by running the CLI once per plan and
subtracting. That approach is identical on both CLI lines.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...errors import CostEstimationError

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

_AUTH_HINTS = (
    "not authenticated",
    "no api key",
    "invalid api key",
    "unauthorized",
    "401",
    "log in",
    "auth login",
    "please sign up",
)


@dataclass(frozen=True)
class InfracostVersion:
    raw: str
    major: int
    minor: int
    patch: int

    @property
    def command_style(self) -> str:
        return "v2" if self.major >= 2 else "v0.10"


class InfracostRunner:
    def __init__(
        self,
        binary: str = "infracost",
        command_style: str = "auto",
        timeout_seconds: int = 300,
        config_file: str | None = None,
        usage_file: str | None = None,
    ) -> None:
        self.binary = binary
        self.configured_style = command_style
        self.timeout_seconds = timeout_seconds
        self.config_file = config_file
        self.usage_file = usage_file
        self._version: InfracostVersion | None = None

    # -- discovery ---------------------------------------------------------
    def resolve_binary(self) -> str:
        resolved = shutil.which(self.binary)
        if resolved:
            return resolved
        candidate = Path(self.binary)
        if candidate.is_file():
            return str(candidate)
        raise CostEstimationError(
            f"Infracost binary '{self.binary}' not found on PATH",
            detail=(
                "Install it from https://www.infracost.io/docs/ and run "
                "`infracost auth login` to get a free API key."
            ),
        )

    def version(self) -> InfracostVersion:
        if self._version is not None:
            return self._version
        proc = self._run([self.resolve_binary(), "--version"], timeout=30)
        match = _VERSION_RE.search(proc.stdout or proc.stderr or "")
        if not match:
            raise CostEstimationError(
                "Could not determine the Infracost CLI version",
                detail=(proc.stdout or proc.stderr or "").strip()[:400],
            )
        self._version = InfracostVersion(
            raw=match.group(0),
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
        )
        return self._version

    def command_style(self) -> str:
        if self.configured_style != "auto":
            return self.configured_style
        return self.version().command_style

    def preflight(self) -> None:
        self.resolve_binary()
        self.version()

    # -- execution ---------------------------------------------------------
    def _run(self, argv: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.setdefault("INFRACOST_NO_COLOR", "true")
        env.setdefault("NO_COLOR", "1")
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise CostEstimationError(
                f"Infracost timed out after {timeout or self.timeout_seconds}s",
                detail=" ".join(argv),
            ) from exc
        except OSError as exc:
            raise CostEstimationError(
                "Failed to execute the Infracost CLI", detail=str(exc)
            ) from exc

    def _build_argv(self, plan_json: Path) -> list[str]:
        binary = self.resolve_binary()
        if self.command_style() == "v2":
            argv = [binary, "scan", str(plan_json), "--json", "--no-color"]
        else:
            argv = [binary, "breakdown", "--path", str(plan_json), "--format", "json", "--no-color"]
        if self.config_file:
            argv += ["--config-file", self.config_file]
        if self.usage_file:
            argv += ["--usage-file", self.usage_file]
        return argv

    def scan_plan(self, plan_json: Path) -> dict:
        """Run Infracost against one Terraform plan JSON and return its document."""
        plan_path = Path(plan_json)
        if not plan_path.is_file():
            raise CostEstimationError(f"Terraform plan JSON not found: {plan_path}")

        proc = self._run(self._build_argv(plan_path))
        stderr = (proc.stderr or "").strip()

        if proc.returncode != 0:
            lowered = stderr.lower()
            if any(hint in lowered for hint in _AUTH_HINTS):
                raise CostEstimationError(
                    "Infracost is not authenticated",
                    detail="Run `infracost auth login`, or set INFRACOST_CLI_AUTHENTICATION_TOKEN in CI.",
                )
            raise CostEstimationError(
                f"Infracost exited with code {proc.returncode}",
                detail=stderr[:800] or (proc.stdout or "")[:800],
            )

        document = _extract_json(proc.stdout or "")
        if document is None:
            raise CostEstimationError(
                "Infracost did not return parseable JSON",
                detail=(proc.stdout or "")[:800],
            )
        return document


def _extract_json(stdout: str) -> dict | None:
    """Tolerate banner text around the JSON body."""
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
