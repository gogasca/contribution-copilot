from pathlib import Path

import pytest

from contrib_pilot.config import load_config
from contrib_pilot.errors import BoundaryViolationError


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".contrib-pilot").mkdir()
    (tmp_path / ".contrib-pilot" / "config.toml").write_text(
        """
schema_version = "1"
working_directory = ".contrib-pilot/runs"
max_changed_files = 6
max_changed_lines = 250

[context]
allowed_sources = ["pkg/a.py", "tests/**"]

[changes]
allowed_paths = ["pkg/a.py", "tests/**"]

[[checks]]
id = "focused-tests"
tier = "fast"
definition = "focused-import-utils-tests"

[[checks]]
id = "gpu-integration"
tier = "ci"
ci_only = true
""",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    return tmp_path


def test_allowed_source_resolves(repo: Path) -> None:
    config = load_config(repo)
    resolved = config.resolve_source("pkg/a.py")
    assert resolved == (repo / "pkg" / "a.py").resolve()


def test_disallowed_source_raises(repo: Path) -> None:
    config = load_config(repo)
    with pytest.raises(BoundaryViolationError):
        config.resolve_source("pkg/b.py")


def test_disallowed_change_path_raises(repo: Path) -> None:
    config = load_config(repo)
    with pytest.raises(BoundaryViolationError):
        config.resolve_change_path("pkg/b.py")


def test_path_escaping_repo_root_raises(repo: Path) -> None:
    config = load_config(repo)
    with pytest.raises(BoundaryViolationError):
        config.resolve_source("../outside.py")


def test_symlink_source_raises(repo: Path) -> None:
    # allowed_sources includes "tests/**"; put the symlink under tests/ so
    # the allowlist check passes and the symlink check is what's exercised.
    (repo / "tests").mkdir()
    outside = repo.parent / "outside.py"
    outside.write_text("z = 1\n", encoding="utf-8")
    link = repo / "tests" / "linked.py"
    link.symlink_to(outside)

    config = load_config(repo)
    with pytest.raises(BoundaryViolationError):
        config.resolve_source("tests/linked.py")


def test_checks_for_tier(repo: Path) -> None:
    config = load_config(repo)
    assert [c.id for c in config.checks_for_tier("fast")] == ["focused-tests"]
    assert {c.id for c in config.checks_for_tier("ci")} == {"focused-tests", "gpu-integration"}
