"""`demo reset` and `doctor`.

``demo reset`` operates only on ``demo/workspace/``, verifies a target
marker file before touching anything, previews affected files, and never
runs a broad Git reset or deletion (plan.MD "Installation, E2E, and Reset
Contract").
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from contrib_pilot.config import find_config
from contrib_pilot.errors import InvalidInputError

WORKSPACE_MARKER = ".contrib-pilot-demo-workspace"


def docs_repo_root(start: Path) -> Path:
    """Locate the package checkout that contains ``demo/fixture-manifest.json``.

    ``demo/workspace`` is its own git repo, so ``git rev-parse --show-toplevel``
    from there is the workspace, not the contrib-pilot checkout. Doctor and
    ``demo reset`` must climb to the checkout that owns the immutable fixture.
    """

    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "demo" / "fixture-manifest.json").is_file():
            return candidate
    return current


@dataclass
class ResetPreview:
    source: Path
    target: Path
    changed_files: list[str]


def _iter_files(root: Path) -> list[Path]:
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]


def preview_reset(demo_dir: Path) -> ResetPreview:
    source = demo_dir / "fixture"
    target = demo_dir / "workspace"
    if not source.is_dir():
        raise InvalidInputError(f"No immutable fixture source at {source}")

    changed: list[str] = []
    for src_file in _iter_files(source):
        rel = src_file.relative_to(source)
        tgt_file = target / rel
        if not tgt_file.is_file() or not filecmp.cmp(src_file, tgt_file, shallow=False):
            changed.append(str(rel))
    return ResetPreview(source=source, target=target, changed_files=changed)


def _force_rmtree(path: Path) -> None:
    """Remove a directory tree, including Windows ReadOnly files and folders.

    OneDrive and git objects commonly set FILE_ATTRIBUTE_READONLY. Plain
    ``shutil.rmtree`` then fails with WinError 5 on ``os.rmdir`` / ``os.unlink``.
    """

    def _onexc(func, p, exc):  # type: ignore[no-untyped-def]
        if not isinstance(exc, PermissionError):
            raise exc
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onexc=_onexc)


def _clear_directory_contents(path: Path) -> None:
    """Delete children of ``path`` but keep ``path`` itself.

    Required on Windows when the shell cwd is the demo workspace: ``rmtree``
    of that directory fails with WinError 32 (directory in use).
    """

    for child in list(path.iterdir()):
        if child.is_dir() and not child.is_symlink():
            _force_rmtree(child)
        else:
            try:
                os.chmod(child, stat.S_IWRITE)
            except OSError:
                pass
            child.unlink()


def _is_replaceable_workspace(target: Path, source: Path) -> bool:
    """True when ``target`` is ours, empty after a failed reset, or only fixture leftovers."""

    if (target / WORKSPACE_MARKER).is_file():
        return True
    names = {child.name for child in target.iterdir()}
    if not names:
        return True
    allowed = {WORKSPACE_MARKER, ".git"} | {child.name for child in source.iterdir()}
    return names <= allowed


def reset(demo_dir: Path) -> ResetPreview:
    preview = preview_reset(demo_dir)
    target = preview.target

    if target.is_dir() and not _is_replaceable_workspace(target, preview.source):
        raise InvalidInputError(
            f"{target} does not look like a managed demo workspace "
            "(missing marker file); refusing to reset it.",
            remediation="Remove or rename the directory manually if this is intentional.",
        )

    if target.is_dir():
        _clear_directory_contents(target)
    shutil.copytree(
        preview.source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )
    (target / WORKSPACE_MARKER).write_text("managed by `contrib-pilot demo reset`\n")
    _init_workspace_repo(target)
    return preview


def _init_workspace_repo(target: Path) -> None:
    """Give the workspace its own throwaway git history.

    Isolated from the outer docs repo: base_commit/diff/changed-paths need
    a real, clean commit to compare against, and the workspace must never
    be mistaken for a submodule of the outer repo (see .gitignore).
    """

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=target, check=True, capture_output=True, timeout=15)

    _git("init", "-q")
    _git("config", "user.email", "demo@contrib-pilot.local")
    _git("config", "user.name", "Contribution Copilot Demo")
    _git("add", "-A")
    _git("commit", "-q", "-m", "Demo fixture starting state")


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def run_doctor(repo_root: Path) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            name="python-version",
            ok=sys.version_info >= (3, 12),
            detail=f"{sys.version_info.major}.{sys.version_info.minor}",
        )
    )

    git_result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
    checks.append(DoctorCheck(name="git", ok=git_result.returncode == 0, detail=git_result.stdout.strip()))

    fixture_config = repo_root / "demo" / "fixture" / ".contrib-pilot" / "config.toml"
    checks.append(
        DoctorCheck(
            name="demo-fixture-config",
            ok=fixture_config.is_file(),
            detail=str(fixture_config) if fixture_config.is_file() else f"not found: {fixture_config}",
        )
    )

    try:
        find_config(repo_root)
        checks.append(DoctorCheck(name="config", ok=True, detail="found .contrib-pilot/config.toml"))
    except InvalidInputError:
        checks.append(
            DoctorCheck(
                name="config",
                ok=True,
                detail="no top-level config (expected — run from demo/workspace after `demo reset`)",
            )
        )

    manifest_path = repo_root / "demo" / "fixture-manifest.json"
    if manifest_path.is_file():
        try:
            json.loads(manifest_path.read_text())
            checks.append(DoctorCheck(name="fixture-manifest", ok=True, detail="valid JSON"))
        except json.JSONDecodeError as exc:
            checks.append(DoctorCheck(name="fixture-manifest", ok=False, detail=str(exc)))
    else:
        checks.append(DoctorCheck(name="fixture-manifest", ok=False, detail="not found"))

    return checks
