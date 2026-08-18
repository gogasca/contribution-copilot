import subprocess
from pathlib import Path

import pytest

from contrib_pilot.config import load_config
from contrib_pilot.errors import InvalidInputError
from contrib_pilot.hooks import install, staged_content_findings, status, uninstall


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".contrib-pilot").mkdir()
    (tmp_path / ".contrib-pilot" / "config.toml").write_text(
        """
schema_version = "1"
working_directory = ".contrib-pilot/runs"
max_changed_files = 6
max_changed_lines = 250

[context]
allowed_sources = ["pkg/a.py"]

[changes]
allowed_paths = ["pkg/a.py"]
""",
        encoding="utf-8",
    )
    return tmp_path


def test_install_requires_confirmation(repo: Path) -> None:
    config = load_config(repo)
    with pytest.raises(InvalidInputError):
        install(config, confirmed=False)


def test_install_sets_hooks_path(repo: Path) -> None:
    config = load_config(repo)
    result = install(config, confirmed=True)
    assert result.managed
    assert result.current_hooks_path == ".contrib-pilot/hooks"


def test_install_refuses_to_replace_existing_hooks_path(repo: Path) -> None:
    subprocess.run(["git", "config", "core.hooksPath", "custom-hooks"], cwd=repo, check=True)
    config = load_config(repo)
    with pytest.raises(InvalidInputError):
        install(config, confirmed=True)


def test_uninstall_clears_managed_hooks_path(repo: Path) -> None:
    config = load_config(repo)
    install(config, confirmed=True)
    result = uninstall(config)
    assert result.current_hooks_path is None


def test_staged_content_findings_flags_boundary_and_prohibited(repo: Path) -> None:
    config = load_config(repo)
    # secrets.env is both outside the allowlist and a prohibited suffix —
    # expect both findings for it, none for the allowed pkg/a.py.
    findings = staged_content_findings(config, ["pkg/outside.py", "secrets.env", "pkg/a.py"])
    rule_ids = [f.rule_id for f in findings]
    assert rule_ids.count("hooks.boundary-violation") == 2
    assert rule_ids.count("hooks.prohibited-file") == 1
    assert len(findings) == 3
