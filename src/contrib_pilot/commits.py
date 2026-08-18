"""Commit-message preparation.

Entirely non-mutating: never stages, commits, or pushes. Only compares the
staged diff, suggests a message, and checks sign-off readiness without
inventing an identity (CUJS.md "From Working Change to Commit and PR").
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from contrib_pilot.git import staged_paths


@dataclass
class SignOffReadiness:
    ready: bool
    name: str | None
    email: str | None


def check_sign_off_readiness(repo: Path) -> SignOffReadiness:
    def _git_config(key: str) -> str | None:
        result = subprocess.run(
            ["git", "config", "--get", key],
            cwd=repo,
            capture_output=True,
            text=True,
            shell=False,
            timeout=5,
        )
        return result.stdout.strip() or None

    name = _git_config("user.name")
    email = _git_config("user.email")
    return SignOffReadiness(ready=bool(name and email), name=name, email=email)


def suggest_commit_message(*, subject_prefix: str, summary: str, criteria_summary: list[str]) -> str:
    body_lines = [summary.strip(), ""]
    body_lines.extend(f"- {c}" for c in criteria_summary)
    return f"{subject_prefix} {summary.splitlines()[0]}\n\n" + "\n".join(body_lines) + "\n"


def planned_vs_staged(*, repo: Path, planned_paths: list[str]) -> dict[str, list[str]]:
    staged = set(staged_paths(repo))
    planned = set(planned_paths)
    return {
        "staged_and_planned": sorted(staged & planned),
        "staged_not_planned": sorted(staged - planned),
        "planned_not_staged": sorted(planned - staged),
    }
