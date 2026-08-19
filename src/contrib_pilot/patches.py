"""Diff generation and safe patch application.

``--dry-run`` never touches tracked files. ``--apply`` rechecks base hashes
immediately before writing, snapshots affected files first, writes through
same-filesystem temp files, and attempts rollback on partial failure —
reporting rollback success explicitly rather than claiming atomicity
(plan.MD "Run Integrity, Ownership, and Staleness").
"""

from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from contrib_pilot.config import Config
from contrib_pilot.errors import StaleStateError
from contrib_pilot.models import ChangePlan, ProposedChange


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def render_unified_diff(config: Config, proposal: ProposedChange) -> str:
    chunks: list[str] = []
    for proposed_file in proposal.files:
        resolved = config.repo_root / proposed_file.path
        before = _current_text(resolved).splitlines(keepends=True)
        after = proposed_file.content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            before,
            after,
            fromfile=f"a/{proposed_file.path}" if before else "/dev/null",
            tofile=f"b/{proposed_file.path}",
        )
        chunks.append("".join(diff))
    return "\n".join(chunk for chunk in chunks if chunk)


def proposal_hash(proposal: ProposedChange) -> str:
    payload = "\x00".join(f"{f.path}\x00{f.content}" for f in proposal.files)
    return _sha256_text(payload)


@dataclass
class BaseStateCheck:
    ok: bool
    changed_paths: list[str]


def check_base_state(config: Config, plan: ChangePlan) -> BaseStateCheck:
    """Verify tracked files still match the hashes recorded at plan time."""

    changed: list[str] = []
    for path_str, expected_hash in plan.base_file_hashes.items():
        resolved = config.repo_root / path_str
        # Hash raw bytes, matching planner/context.file_hash. read_text()
        # translates CRLF to LF on Windows, which would false-stale every apply.
        current = hashlib.sha256(resolved.read_bytes()).hexdigest() if resolved.is_file() else "<missing>"
        if current != expected_hash:
            changed.append(path_str)
    return BaseStateCheck(ok=not changed, changed_paths=changed)


@dataclass
class ApplyResult:
    applied_paths: list[str]
    rollback_attempted: bool = False
    rollback_succeeded: bool | None = None
    error: str | None = None


def apply_proposal(config: Config, plan: ChangePlan, proposal: ProposedChange) -> ApplyResult:
    base_check = check_base_state(config, plan)
    if not base_check.ok:
        raise StaleStateError(
            f"Base state changed since planning: {', '.join(base_check.changed_paths)}",
            remediation="Re-run `contrib-pilot plan` to refresh the base state, then re-propose.",
        )

    resolved_targets = [(f, config.repo_root / f.path) for f in proposal.files]
    snapshots: dict[Path, str | None] = {
        resolved: (_current_text(resolved) if resolved.is_file() else None)
        for _, resolved in resolved_targets
    }

    applied: list[str] = []
    try:
        for proposed_file, resolved in resolved_targets:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(resolved, proposed_file.content)
            applied.append(str(proposed_file.path))
        return ApplyResult(applied_paths=applied)
    except OSError as exc:
        rollback_ok = _rollback(snapshots)
        return ApplyResult(
            applied_paths=applied,
            rollback_attempted=True,
            rollback_succeeded=rollback_ok,
            error=str(exc),
        )


def _atomic_write(target: Path, content: str) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, target)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _rollback(snapshots: dict[Path, str | None]) -> bool:
    ok = True
    for resolved, previous_content in snapshots.items():
        try:
            if previous_content is None:
                if resolved.is_file():
                    resolved.unlink()
            else:
                _atomic_write(resolved, previous_content)
        except OSError:
            ok = False
    return ok
