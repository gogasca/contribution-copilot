from pathlib import Path

import pytest

from contrib_pilot.config import init_repo, load_config
from contrib_pilot.errors import BoundaryViolationError
from contrib_pilot.validation import CHECK_REGISTRY


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


def test_windows_separators_match_posix_allowlist(repo: Path) -> None:
    config = load_config(repo)
    resolved = config.resolve_source(r"pkg\a.py")
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


def test_example_config_loads_and_registry_keys_exist(tmp_path: Path) -> None:
    config, created = init_repo(tmp_path)
    assert created is True
    assert config.schema_version == "1"
    assert "src/**" in config.allowed_paths
    for check in config.checks:
        if check.definition is not None:
            assert check.definition in CHECK_REGISTRY
    assert "libs.no-new-third-party" in config.convention_rules
    assert (tmp_path / ".contrib-pilot" / "runs").is_dir()


def test_init_repo_does_not_replace_existing_policy(tmp_path: Path) -> None:
    existing = tmp_path / ".contrib-pilot"
    existing.mkdir()
    (existing / "config.toml").write_text(
        'schema_version = "1"\nworking_directory = ".contrib-pilot/runs"\n'
        "max_changed_files = 1\nmax_changed_lines = 10\n"
        '[context]\nallowed_sources = ["src/**"]\n'
        '[changes]\nallowed_paths = ["src/**"]\n',
        encoding="utf-8",
    )
    config, created = init_repo(tmp_path)
    assert created is False
    assert config.max_changed_files == 1
    assert config.max_changed_lines == 10
