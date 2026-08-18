"""End-to-end: issue -> plan -> dry-run diff -> approve/apply -> validate -> review -> report.

Runs against a temporary copy of the real bundled demo fixture so the test
suite never mutates the repository's own demo/workspace/.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from contrib_pilot import orchestrator
from contrib_pilot.config import load_config
from contrib_pilot.models import Stage
from contrib_pilot.providers.fixture import FixtureProvider

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def demo_workspace(tmp_path: Path) -> Path:
    fixture_src = REPO_ROOT / "demo" / "fixture"
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture_src, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=workspace, check=True)
    return workspace


@pytest.fixture
def expected_dir() -> Path:
    return REPO_ROOT / "demo" / "expected"


def test_full_flow_reaches_reported(demo_workspace: Path, expected_dir: Path) -> None:
    config = load_config(demo_workspace)
    provider = FixtureProvider(expected_dir=expected_dir)
    issue_path = REPO_ROOT / "demo" / "issue.md"
    source_purposes = {
        "vllm/utils/import_utils.py": "implementation file under change",
        "tests/utils_/test_import_utils.py": "nearest existing test module",
    }

    result = orchestrator.run(
        config=config,
        issue_path=issue_path,
        provider=provider,
        source_purposes=source_purposes,
        confirm=lambda _msg: True,
        run_id="e2e-test",
    )

    assert result.state.stage is Stage.REPORTED, result.reason
    assert not result.paused

    report_md = Path(result.state.artifact_paths["report_md"]).read_text()
    assert "Contribution Report" in report_md
    assert "**Ready**" in report_md

    changed = subprocess.run(
        ["git", "diff", "--name-only"], cwd=demo_workspace, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "vllm/utils/import_utils.py" in changed
    assert "tests/utils_/test_import_utils.py" in changed


def test_pytest_actually_passes_after_apply(demo_workspace: Path, expected_dir: Path) -> None:
    """The fixture's own real pytest run must pass after the patch is applied."""

    config = load_config(demo_workspace)
    provider = FixtureProvider(expected_dir=expected_dir)
    issue_path = REPO_ROOT / "demo" / "issue.md"
    source_purposes = {
        "vllm/utils/import_utils.py": "implementation file under change",
        "tests/utils_/test_import_utils.py": "nearest existing test module",
    }

    result = orchestrator.run(
        config=config,
        issue_path=issue_path,
        provider=provider,
        source_purposes=source_purposes,
        confirm=lambda _msg: True,
        run_id="e2e-pytest",
    )
    assert result.state.stage is Stage.REPORTED, result.reason

    # Scoped to the tests this change touches — the file's other tests
    # (e.g. PlaceholderModule) depend on a full vLLM install and are
    # unrelated to this change (see validation.CHECK_REGISTRY).
    validation = subprocess.run(
        ["python", "-m", "pytest", "tests/utils_/test_import_utils.py::TestResolveObjByQualname", "-q"],
        cwd=demo_workspace,
        capture_output=True,
        text=True,
    )
    assert validation.returncode == 0, validation.stdout + validation.stderr
