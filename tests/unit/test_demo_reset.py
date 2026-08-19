import os
import stat
from pathlib import Path

import pytest

from contrib_pilot.demo import WORKSPACE_MARKER, docs_repo_root, reset
from contrib_pilot.errors import InvalidInputError


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    demo = tmp_path / "demo"
    fixture = demo / "fixture"
    (fixture / "pkg").mkdir(parents=True)
    (fixture / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return demo


def test_reset_creates_workspace_with_marker_and_git_history(demo_dir: Path) -> None:
    preview = reset(demo_dir)
    workspace = demo_dir / "workspace"
    assert (workspace / WORKSPACE_MARKER).is_file()
    assert (workspace / ".git").is_dir()
    assert (workspace / "pkg" / "a.py").read_text() == "x = 1\n"
    assert any(Path(p).as_posix() == "pkg/a.py" for p in preview.changed_files)


def test_reset_refuses_unmanaged_directory(demo_dir: Path) -> None:
    workspace = demo_dir / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "unrelated.txt").write_text("do not touch\n", encoding="utf-8")

    with pytest.raises(InvalidInputError):
        reset(demo_dir)

    assert (workspace / "unrelated.txt").is_file()


def test_reset_recovers_empty_workspace_without_marker(demo_dir: Path) -> None:
    workspace = demo_dir / "workspace"
    workspace.mkdir(parents=True)
    preview = reset(demo_dir)
    assert (workspace / WORKSPACE_MARKER).is_file()
    assert (workspace / "pkg" / "a.py").read_text() == "x = 1\n"
    assert preview.target == workspace


def test_reset_is_idempotent(demo_dir: Path) -> None:
    reset(demo_dir)
    (demo_dir / "workspace" / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    reset(demo_dir)
    assert (demo_dir / "workspace" / "pkg" / "a.py").read_text() == "x = 1\n"


def test_reset_removes_readonly_empty_run_dir(demo_dir: Path) -> None:
    reset(demo_dir)
    current = demo_dir / "workspace" / ".contrib-pilot" / "runs" / "current"
    current.mkdir(parents=True, exist_ok=True)
    os.chmod(current, stat.S_IREAD)
    reset(demo_dir)
    assert (demo_dir / "workspace" / "pkg" / "a.py").read_text() == "x = 1\n"


def test_docs_repo_root_climbs_out_of_nested_workspace(tmp_path: Path) -> None:
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "fixture-manifest.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "demo" / "workspace"
    workspace.mkdir()
    assert docs_repo_root(workspace) == tmp_path.resolve()


def test_reset_succeeds_when_cwd_is_the_workspace(demo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset(demo_dir)
    workspace = demo_dir / "workspace"
    (workspace / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    monkeypatch.chdir(workspace)
    reset(demo_dir)
    assert (workspace / "pkg" / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (workspace / WORKSPACE_MARKER).is_file()
