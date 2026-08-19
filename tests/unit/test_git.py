import subprocess
from pathlib import Path

from contrib_pilot.git import changed_paths, contribution_changed_paths


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_changed_paths_includes_untracked_new_tests(tmp_path: Path) -> None:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "test@example.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    (tmp_path / "tracked.py").write_text("a = 1\n", encoding="utf-8")
    _git(["add", "tracked.py"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    (tmp_path / "tracked.py").write_text("a = 2\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    paths = changed_paths(tmp_path)
    assert "tracked.py" in paths
    assert "tests/test_new.py" in paths or "tests\\test_new.py" in paths


def test_contribution_changed_paths_skips_tool_artifacts_and_issue(tmp_path: Path) -> None:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "test@example.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "pkg/mod.py"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)

    (tmp_path / "pkg" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "issue.md").write_text("1. fix it\n", encoding="utf-8")
    (tmp_path / ".contrib-pilot").mkdir()
    (tmp_path / ".contrib-pilot" / "config.toml").write_text("schema_version = \"1\"\n", encoding="utf-8")
    (tmp_path / ".contrib-pilot" / "runs").mkdir()
    (tmp_path / ".contrib-pilot" / "runs" / "current").mkdir()
    (tmp_path / ".contrib-pilot" / "runs" / "current" / "plan.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pkg" / "__pycache__").mkdir()
    (tmp_path / "pkg" / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\0")

    raw = changed_paths(tmp_path)
    assert any(p.replace("\\", "/").endswith("issue.md") for p in raw)
    assert any(".contrib-pilot" in p.replace("\\", "/") for p in raw)

    contrib = contribution_changed_paths(tmp_path, issue_path=tmp_path / "issue.md")
    posix = [p.replace("\\", "/") for p in contrib]
    assert "pkg/mod.py" in posix
    assert "issue.md" not in posix
    assert not any(p == ".contrib-pilot" or p.startswith(".contrib-pilot/") for p in posix)
    assert not any("__pycache__" in p or p.endswith(".pyc") for p in posix)
