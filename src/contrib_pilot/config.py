"""Load and validate ``.contrib-pilot/config.toml``.

This module is the deterministic boundary authority: every other module asks
it whether a path is allowed rather than re-implementing the allowlist logic
(see plan.MD "Approved Context and Guardrails" and "Safe Command Execution").
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from contrib_pilot.conventions import RULE_REGISTRY
from contrib_pilot.errors import BoundaryViolationError, InvalidInputError

CONFIG_RELATIVE_PATH = Path(".contrib-pilot/config.toml")
RUNS_RELATIVE_PATH = Path(".contrib-pilot/runs")
EXAMPLE_CONFIG_RELATIVE = Path("examples/config.toml")


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
    convention_rules: tuple[str, ...] = ()
    first_party_prefixes: tuple[str, ...] = ()
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

    @staticmethod
    def _posix(relative_path: str) -> str:
        return relative_path.replace("\\", "/")

    def is_allowed_source(self, relative_path: str) -> bool:
        relative_path = self._posix(relative_path)
        return any(fnmatch(relative_path, self._posix(pattern)) for pattern in self.allowed_sources)

    def is_allowed_change_path(self, relative_path: str) -> bool:
        relative_path = self._posix(relative_path)
        return any(fnmatch(relative_path, self._posix(pattern)) for pattern in self.allowed_paths)

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


def example_config_template() -> Path:
    """Return the generic policy shipped in this checkout.

    ``src/contrib_pilot/config.py`` → repo root is two parents up.
    """

    checkout = Path(__file__).resolve().parents[2]
    path = checkout / EXAMPLE_CONFIG_RELATIVE
    if not path.is_file():
        raise InvalidInputError(
            f"Bundled example config not found at {path}",
            remediation="Run from a contrib-pilot source checkout, or copy examples/config.toml manually.",
        )
    return path


def find_config(start: Path) -> Path:
    candidate = start / CONFIG_RELATIVE_PATH
    if not candidate.is_file():
        raise InvalidInputError(
            f"No configuration found at {candidate}",
            remediation="Run `contrib-pilot init` from the repository root.",
        )
    return candidate


def init_repo(repo_root: Path) -> tuple[Config, bool]:
    """Ensure policy exists and create the ignored run directory.

    Copies ``examples/config.toml`` only when the target has no config.
    Never replaces an existing policy file (DESIGN.md init mutation class).
    """

    repo_root = repo_root.resolve()
    config_path = repo_root / CONFIG_RELATIVE_PATH
    created = False
    if not config_path.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example_config_template(), config_path)
        created = True
    config = load_config(repo_root)
    config.working_directory.mkdir(parents=True, exist_ok=True)
    return config, created


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

    conventions = raw.get("conventions", {})
    convention_rules = tuple(conventions.get("rules", ()))
    unknown = [rule_id for rule_id in convention_rules if rule_id not in RULE_REGISTRY]
    if unknown:
        raise InvalidInputError(
            f"Unknown convention rule id(s): {', '.join(unknown)}",
            remediation="Use a key from contrib_pilot.conventions.RULE_REGISTRY, or remove it from [conventions].rules.",
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
        convention_rules=convention_rules,
        first_party_prefixes=tuple(conventions.get("first_party_prefixes", ())),
    )
