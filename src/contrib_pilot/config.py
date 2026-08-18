"""Load and validate ``.contrib-pilot/config.toml``.

This module is the deterministic boundary authority: every other module asks
it whether a path is allowed rather than re-implementing the allowlist logic
(see plan.MD "Approved Context and Guardrails" and "Safe Command Execution").
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from contrib_pilot.errors import BoundaryViolationError, InvalidInputError

CONFIG_RELATIVE_PATH = Path(".contrib-pilot/config.toml")
RUNS_RELATIVE_PATH = Path(".contrib-pilot/runs")


@dataclass(frozen=True)
class CheckDefinition:
    """A configured check.

    ``definition`` is a key into ``validation.CHECK_REGISTRY`` — the
    checked-in executable/argument mapping. config.toml never carries a raw
    command array: introducing a new executable means adding a registry
    entry in code, which goes through normal review (plan.MD "Safe Command
    Execution").
    """

    id: str
    tier: str
    ci_only: bool = False
    definition: str | None = None  # None only for ci_only checks with no local run
    append_changed_files: bool = False
    timeout_seconds: int = 60


@dataclass(frozen=True)
class Config:
    repo_root: Path
    schema_version: str
    working_directory: Path
    max_changed_files: int
    max_changed_lines: int
    allowed_sources: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    checks: tuple[CheckDefinition, ...]
    allowed_executables: tuple[str, ...] = field(
        default_factory=lambda: ("python", "python3", "uv", "git")
    )

    def checks_for_tier(self, tier: str) -> list[CheckDefinition]:
        if tier == "fast":
            return [c for c in self.checks if c.tier == "fast"]
        if tier == "ci":
            return list(self.checks)
        raise InvalidInputError(f"Unknown validation tier: {tier!r}")

    def _resolve_within_repo(self, relative: str | Path) -> Path:
        candidate = (self.repo_root / relative).resolve()
        try:
            candidate.relative_to(self.repo_root.resolve())
        except ValueError as exc:
            raise BoundaryViolationError(
                f"Path escapes the repository root: {relative}",
                remediation="Use a path inside the repository.",
            ) from exc
        if candidate.is_symlink():
            raise BoundaryViolationError(
                f"Path is a symlink, which is not permitted: {relative}",
                remediation="Replace the symlink with a regular file, or exclude it.",
            )
        return candidate

    def is_allowed_source(self, relative_path: str) -> bool:
        return any(fnmatch(relative_path, pattern) for pattern in self.allowed_sources)

    def is_allowed_change_path(self, relative_path: str) -> bool:
        return any(fnmatch(relative_path, pattern) for pattern in self.allowed_paths)

    def resolve_source(self, relative_path: str) -> Path:
        if not self.is_allowed_source(relative_path):
            raise BoundaryViolationError(
                f"Source path is outside the approved context allowlist: {relative_path}",
                remediation=(
                    "Add the path to [context].allowed_sources in "
                    "config.toml if it should be readable, or choose an "
                    "already-approved source."
                ),
            )
        return self._resolve_within_repo(relative_path)

    def resolve_change_path(self, relative_path: str) -> Path:
        if not self.is_allowed_change_path(relative_path):
            raise BoundaryViolationError(
                f"Change path is outside the allowlist: {relative_path}",
                remediation=(
                    "Add the path to [changes].allowed_paths in "
                    "config.toml, or re-plan within the existing scope."
                ),
            )
        return self._resolve_within_repo(relative_path)


def find_config(start: Path) -> Path:
    candidate = start / CONFIG_RELATIVE_PATH
    if not candidate.is_file():
        raise InvalidInputError(
            f"No configuration found at {candidate}",
            remediation="Run `contrib-pilot init` from the repository root.",
        )
    return candidate


def load_config(repo_root: Path) -> Config:
    config_path = find_config(repo_root)
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    checks = tuple(
        CheckDefinition(
            id=c["id"],
            tier=c["tier"],
            ci_only=c.get("ci_only", False),
            definition=c.get("definition"),
            append_changed_files=c.get("append_changed_files", False),
            timeout_seconds=c.get("timeout_seconds", 60),
        )
        for c in raw.get("checks", [])
    )

    return Config(
        repo_root=repo_root.resolve(),
        schema_version=str(raw.get("schema_version", "1")),
        working_directory=repo_root / raw.get("working_directory", ".contrib-pilot/runs"),
        max_changed_files=raw.get("max_changed_files", 6),
        max_changed_lines=raw.get("max_changed_lines", 250),
        allowed_sources=tuple(raw.get("context", {}).get("allowed_sources", ())),
        allowed_paths=tuple(raw.get("changes", {}).get("allowed_paths", ())),
        checks=checks,
    )
