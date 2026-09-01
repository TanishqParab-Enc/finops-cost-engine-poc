"""Component A - decide whether a PR can affect cloud consumption.

Uses git to list changed files and matches them against configured globs. If no
infrastructure file changed the gate is skipped entirely, so non-infra PRs are
not slowed down.
"""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..config import ChangeDetectionConfig
from ..errors import PlanError


@dataclass
class ChangeDetectionResult:
    has_infrastructure_changes: bool
    infrastructure_files: list[str] = field(default_factory=list)
    other_files: list[str] = field(default_factory=list)
    base_ref: str = ""
    head_ref: str = ""

    def to_dict(self) -> dict:
        return {
            "has_infrastructure_changes": self.has_infrastructure_changes,
            "infrastructure_files": self.infrastructure_files,
            "other_files_count": len(self.other_files),
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
        }


def _matches_any(path: str, patterns: list[str]) -> bool:
    posix = PurePosixPath(path.replace("\\", "/")).as_posix()
    for pattern in patterns:
        if fnmatch.fnmatch(posix, pattern):
            return True
        # "**/*.tf" should also match a file at the repo root.
        if pattern.startswith("**/") and fnmatch.fnmatch(posix, pattern[3:]):
            return True
    return False


def classify_files(files: list[str], config: ChangeDetectionConfig) -> ChangeDetectionResult:
    infra: list[str] = []
    other: list[str] = []
    for path in files:
        if not path:
            continue
        if _matches_any(path, config.ignore_globs):
            other.append(path)
        elif _matches_any(path, config.infrastructure_globs):
            infra.append(path)
        else:
            other.append(path)
    return ChangeDetectionResult(
        has_infrastructure_changes=bool(infra),
        infrastructure_files=sorted(infra),
        other_files=sorted(other),
    )


def git_changed_files(base_ref: str, head_ref: str = "HEAD", repo_dir: str = ".") -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PlanError("git is not available on PATH", detail=str(exc)) from exc

    if proc.returncode != 0:
        # Fall back to a two-dot diff, which works when there is no merge base.
        proc = subprocess.run(
            ["git", "diff", "--name-only", base_ref, head_ref],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise PlanError(
                f"git diff failed between {base_ref} and {head_ref}",
                detail=proc.stderr.strip(),
            )

    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def detect_changes(
    config: ChangeDetectionConfig,
    base_ref: str,
    head_ref: str = "HEAD",
    repo_dir: str = ".",
) -> ChangeDetectionResult:
    result = classify_files(git_changed_files(base_ref, head_ref, repo_dir), config)
    result.base_ref = base_ref
    result.head_ref = head_ref
    return result
