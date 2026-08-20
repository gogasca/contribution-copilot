import os
from pathlib import Path
from unittest.mock import MagicMock

from contrib_pilot.config import CheckDefinition
from contrib_pilot.models import Severity
from contrib_pilot.validation import (
    CHECK_REGISTRY,
    _resolve_command,
    _sanitized_env,
    _unimportable_dash_m_module,
    run_check,
)


def test_sanitized_env_disables_pytest_plugin_autoload() -> None:
    env = _sanitized_env()
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "ANTHROPIC_API_KEY" not in env
    assert "PYTHONPATH" not in env


def test_sanitized_env_puts_src_on_pythonpath(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    env = _sanitized_env(tmp_path)
    assert env["PYTHONPATH"] == str(tmp_path / "src")


def test_sanitized_env_keeps_windows_systemroot() -> None:
    env = _sanitized_env()
    names = {key.upper() for key in env}
    if os.name == "nt":
        assert "SYSTEMROOT" in names
    assert "ANTHROPIC_API_KEY" not in names


def test_focused_tests_skip_conftest() -> None:
    check = CheckDefinition(
        id="focused-tests",
        tier="fast",
        definition="focused-import-utils-tests",
    )
    command = _resolve_command(check, [])
    assert "--noconftest" in command
    assert CHECK_REGISTRY["focused-import-utils-tests"][-1] == "--noconftest"


def test_pytest_fast_is_generic_pytest() -> None:
    check = CheckDefinition(id="focused-tests", tier="fast", definition="pytest-fast")
    command = _resolve_command(check, [])
    assert command[-2:] == ["pytest", "-q"]
    assert "--noconftest" not in command


def test_pytest_planned_tests_inserts_plan_paths() -> None:
    check = CheckDefinition(id="focused-tests", tier="fast", definition="pytest-planned-tests")
    command = _resolve_command(check, [], ["tests/v1/core/test_dspark_input_budget.py"])
    assert "tests/v1/core/test_dspark_input_budget.py" in command
    assert "--noconftest" in command
    assert "{planned_tests}" not in command
    assert "pytest_asyncio.plugin" in command


def test_pytest_planned_tests_prefer_src_layout(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    check = CheckDefinition(id="focused-tests", tier="fast", definition="pytest-planned-tests")
    command = _resolve_command(check, [], ["tests/test_foo.py"], repo_root=tmp_path)
    assert "-c" in command
    assert "sys.path" in command[command.index("-c") + 1]
    assert "-m" not in command


def test_missing_dash_m_module_is_ci_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "contrib_pilot.validation.importlib.util.find_spec",
        lambda name: None if name == "pre_commit" else MagicMock(),
    )
    check = CheckDefinition(
        id="pre-commit",
        tier="fast",
        definition="project-pre-commit-changed-files",
        append_changed_files=True,
    )
    command = _resolve_command(check, ["pkg/a.py"])
    assert _unimportable_dash_m_module(command) == "pre_commit"

    config = MagicMock()
    config.repo_root = tmp_path
    result = run_check(config, check, ["pkg/a.py"])
    assert result.status is Severity.CI_REQUIRED
    assert "pre_commit" in result.output_excerpt
