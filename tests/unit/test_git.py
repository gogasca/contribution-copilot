import subprocess
from pathlib import Path

from contrib_pilot.git import changed_paths


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
