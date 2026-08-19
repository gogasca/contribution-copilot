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
    """Working-tree, staged, and untracked paths. New planned tests are often untracked."""

    names: list[str] = []
    seen: set[str] = set()
    for args in (
        ["diff", "--name-only"],
        ["diff", "--cached", "--name-only"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        for line in _run(args, cwd=repo).splitlines():
            if line and line not in seen:
                seen.add(line)
                names.append(line)
    return names


def _repo_posix(repo: Path, path: Path | str) -> str:
    """Normalize a path to repo-relative POSIX form for comparisons."""

    candidate = Path(str(path))
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
        return resolved.relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix().replace("\\", "/")


def _is_non_contribution(posix: str, issue: str | None) -> bool:
    if posix == ".contrib-pilot" or posix.startswith(".contrib-pilot/"):
        return True
    if posix == ".pytest_cache" or posix.startswith(".pytest_cache/"):
        return True
    if "__pycache__" in posix.split("/") or posix.endswith((".pyc", ".pyo")):
        return True
    return bool(issue and posix == issue)


def contribution_changed_paths(
    repo: Path, *, issue_path: Path | str | None = None
) -> list[str]:
    """Changed paths that are part of the contribution, not tool/run inputs.

    ``.contrib-pilot/**``, the plan's issue file, and interpreter caches are
    working inputs, not files the contribution is allowed to change.
    """

    issue = _repo_posix(repo, issue_path) if issue_path is not None else None
    kept: list[str] = []
    for path in changed_paths(repo):
        posix = _repo_posix(repo, path)
        if _is_non_contribution(posix, issue):
            continue
        kept.append(path)
    return kept


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
