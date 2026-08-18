"""Read-only Git wrapper.

Every call is an argument list with ``shell=False`` — no shell string is ever
built from user or repository content. This module never stages, commits,
pushes, or resets anything (see plan.MD "Safe Command Execution").
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        shell=False,
        timeout=15,
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repo_root(start: Path) -> Path:
    return Path(_run(["rev-parse", "--show-toplevel"], cwd=start))


def base_commit(repo: Path) -> str:
    return _run(["rev-parse", "HEAD"], cwd=repo)


def working_tree_diff(repo: Path) -> str:
    return _run(["diff"], cwd=repo)


def staged_diff(repo: Path) -> str:
    return _run(["diff", "--cached"], cwd=repo)


def changed_paths(repo: Path) -> list[str]:
    out = _run(["diff", "--name-only"], cwd=repo)
    return [line for line in out.splitlines() if line]


def staged_paths(repo: Path) -> list[str]:
    out = _run(["diff", "--cached", "--name-only"], cwd=repo)
    return [line for line in out.splitlines() if line]


def untracked_paths(repo: Path) -> list[str]:
    out = _run(["ls-files", "--others", "--exclude-standard"], cwd=repo)
    return [line for line in out.splitlines() if line]


def hooks_path(repo: Path) -> str | None:
    try:
        return _run(["config", "--get", "core.hooksPath"], cwd=repo)
    except GitError:
        return None


def diff_hash(repo: Path, *, staged: bool = False) -> str:
    import hashlib

    content = staged_diff(repo) if staged else working_tree_diff(repo)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
