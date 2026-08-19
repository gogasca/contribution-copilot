"""Smoke tests that actually invoke the Typer app.

Unlike the other unit tests, which call engine functions directly, this
module exists specifically to catch CLI-wiring bugs (decorators that break
Typer's signature introspection, command name collisions, syntax errors)
that calling the engine directly would never exercise.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contrib_pilot.cli import app

runner = CliRunner()


def test_help_lists_all_top_level_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "plan", "scaffold", "validate", "review", "report", "run", "doctor", "hook"):
        assert command in result.output
    for group in ("hooks", "demo", "commit"):
        assert group in result.output


def test_doctor_runs_without_crashing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor"], catch_exceptions=False)
    assert result.exit_code in (0, 2)  # 2 only if this checkout is missing something


def test_init_copies_example_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--path", str(tmp_path)], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "examples/config.toml" in result.output
    copied = tmp_path / ".contrib-pilot" / "config.toml"
    assert copied.is_file()
    assert "pytest-fast" in copied.read_text(encoding="utf-8")

    again = runner.invoke(app, ["init", "--path", str(tmp_path)], catch_exceptions=False)
    assert again.exit_code == 0, again.output
    assert "examples/config.toml" not in again.output


def test_demo_reset_and_full_flow_via_cli(tmp_path: Path) -> None:
    """Drive the whole documented walkthrough through the real CLI entrypoints."""

    repo_root = Path(__file__).resolve().parents[2]

    def run(args: list[str], cwd: Path, input_text: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["uv", "run", "--project", str(repo_root), "contrib-pilot", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=60,
        )

    reset_result = run(["demo", "reset"], cwd=repo_root)
    assert reset_result.returncode == 0, reset_result.stderr

    workspace = repo_root / "demo" / "workspace"
    issue = repo_root / "demo" / "issue.md"

    plan_result = run(["plan", str(issue), "--provider", "fixture"], cwd=workspace)
    assert plan_result.returncode == 0, plan_result.stderr

    dry_run_result = run(["scaffold", "--dry-run", "--provider", "fixture"], cwd=workspace)
    assert dry_run_result.returncode == 0, dry_run_result.stderr
    assert "resolve_obj_by_qualname" in dry_run_result.stdout

    apply_result = run(["scaffold", "--apply", "--yes"], cwd=workspace)
    assert apply_result.returncode == 0, apply_result.stderr

    validate_result = run(["validate", "--tier", "fast"], cwd=workspace)
    assert validate_result.returncode == 0, validate_result.stderr

    review_result = run(["review"], cwd=workspace)
    assert review_result.returncode == 0, review_result.stderr
    assert "Ready: True" in review_result.stdout

    report_result = run(["report", "--provider", "fixture"], cwd=workspace)
    assert report_result.returncode == 0, report_result.stderr
    assert "Ready" in report_result.stdout

    # Leave the fixture clean for the next run/human demo.
    run(["demo", "reset"], cwd=repo_root)
