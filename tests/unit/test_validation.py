import os

from contrib_pilot.config import CheckDefinition
from contrib_pilot.validation import CHECK_REGISTRY, _resolve_command, _sanitized_env


def test_sanitized_env_disables_pytest_plugin_autoload() -> None:
    env = _sanitized_env()
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "ANTHROPIC_API_KEY" not in env


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
