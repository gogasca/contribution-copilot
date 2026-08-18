"""Bounded, allowlisted context discovery.

This is the only module that reads governed context for the planner and
providers. It resolves and validates every path through ``Config`` before
opening it, and returns structured evidence rather than an unbounded prompt
string (plan.MD "Approved Context and Guardrails").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from contrib_pilot.config import Config
from contrib_pilot.models import SourceEvidence

MAX_TOTAL_CONTEXT_BYTES = 500_000
MAX_FILE_CONTEXT_BYTES = 100_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def discover_sources(config: Config, purposes: dict[str, str]) -> list[SourceEvidence]:
    """Resolve a mapping of {relative_path: purpose} into hashed evidence.

    Every path must already be inside ``config.allowed_sources``; a path
    that fails the allowlist is skipped rather than silently expanded, and
    the caller (``planner``) is responsible for treating a missing required
    source as a stop condition, not an invented convention.
    """

    evidence: list[SourceEvidence] = []
    total_bytes = 0

    for relative_path, purpose in purposes.items():
        resolved = config.resolve_source(relative_path)
        if not resolved.is_file():
            continue
        data = resolved.read_bytes()
        if len(data) > MAX_FILE_CONTEXT_BYTES:
            data = data[:MAX_FILE_CONTEXT_BYTES]
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_CONTEXT_BYTES:
            break
        evidence.append(
            SourceEvidence(path=Path(relative_path), sha256=_sha256(data), purpose=purpose)
        )

    return evidence


def read_approved(config: Config, relative_path: str) -> str:
    """Read one allowlisted source file's text content.

    Raises the same ``BoundaryViolationError`` as ``Config.resolve_source``
    for anything outside the allowlist — there is no fallback read path.
    """

    resolved = config.resolve_source(relative_path)
    return resolved.read_text(encoding="utf-8")


def file_hash(config: Config, relative_path: str) -> str:
    resolved = config.resolve_source(relative_path)
    return _sha256(resolved.read_bytes())
