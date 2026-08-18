from pathlib import Path

import pytest

from contrib_pilot.demo import WORKSPACE_MARKER, reset
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
    assert "pkg/a.py" in preview.changed_files


def test_reset_refuses_unmanaged_directory(demo_dir: Path) -> None:
    workspace = demo_dir / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "unrelated.txt").write_text("do not touch\n", encoding="utf-8")

    with pytest.raises(InvalidInputError):
        reset(demo_dir)

    assert (workspace / "unrelated.txt").is_file()


def test_reset_is_idempotent(demo_dir: Path) -> None:
    reset(demo_dir)
    (demo_dir / "workspace" / "pkg" / "a.py").write_text("x = 999\n", encoding="utf-8")
    reset(demo_dir)
    assert (demo_dir / "workspace" / "pkg" / "a.py").read_text() == "x = 1\n"
