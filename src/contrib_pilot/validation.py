"""Check selection, safe execution, and classification.

Commands run as argument arrays with ``shell=False``, an explicit working
directory, an allowlisted environment, and per-command/total timeouts
(plan.MD "Safe Command Execution"). ``CHECK_REGISTRY`` is the one place a
check id resolves to an executable — config.toml can only reference a
registry key, never raw command text.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from contrib_pilot.config import CheckDefinition, Config
from contrib_pilot.conventions import evaluate as evaluate_conventions
from contrib_pilot.models import ChangePlan, CommandResult, Finding, Severity, ValidationReport

MAX_OUTPUT_BYTES = 20_000
_ALLOWED_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "HOME",
    "VIRTUAL_ENV",
    # Windows Winsock/asyncio need these. Omitting SYSTEMROOT makes
    # `import unittest.mock` raise WinError 10106, so focused pytest
    # collection fails before any test runs.
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
)

# Checked-in registry: check "definition" -> argument template. `{python}` is
# substituted with the active interpreter; `{changed_files}` is substituted
# only when the check's `append_changed_files` flag is set.
CHECK_REGISTRY: dict[str, list[str]] = {
    # Scoped to the tests this change actually touches. The rest of
    # test_import_utils.py (e.g. PlaceholderModule's package-metadata
    # lookup) depends on a full vLLM install and is unrelated to this
    # change — running it would fail on environment grounds, not on the
    # change's own correctness.
    "focused-import-utils-tests": [
        "{python}",
        "-m",
        "pytest",
        "tests/utils_/test_import_utils.py::TestResolveObjByQualname",
        "-q",
        "--noconftest",
    ],
    "project-pre-commit-changed-files": [
        "{python}",
        "-m",
        "pre_commit",
        "run",
        "--files",
    ],
    # Full-suite pytest. Needs the target project's test extra (conftest
    # deps included). Prefer pytest-planned-tests unless that env exists.
    "pytest-fast": [
        "{python}",
        "-m",
        "pytest",
        "-q",
    ],
    # Default for a real clone: only the plan's test files, and skip the
    # target's conftest so missing extras (e.g. vLLM's tblib) do not fail
    # collection before the focused tests run.
    "pytest-planned-tests": [
        "{python}",
        "-m",
        "pytest",
        "{planned_tests}",
        "-q",
        "--noconftest",
    ],
}


def _sanitized_env(repo_root: Path | None = None) -> dict[str, str]:
    allowed = {key.upper() for key in _ALLOWED_ENV_KEYS}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    # Keep pytest from auto-loading third-party plugins (e.g. anyio) that are
    # installed into this interpreter but are unrelated to the focused tests.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if repo_root is not None:
        src = repo_root / "src"
        if src.is_dir():
            # Prefer src/ over a same-named package at the repo root. Do not
            # also put the root on PYTHONPATH or the two trees merge.
            env["PYTHONPATH"] = str(src)
    return env


def _unimportable_dash_m_module(command: list[str]) -> str | None:
    """Return ``-m`` module name when the active interpreter cannot import it."""

    try:
        flag_at = command.index("-m")
    except ValueError:
        return None
    if flag_at + 1 >= len(command):
        return None
    module = command[flag_at + 1]
    if command[0] != sys.executable:
        return None
    if importlib.util.find_spec(module) is None:
        return module
    return None


# `python -m pytest` puts cwd (the repo root) first on sys.path. For a src/
# layout that shadows a same-named root package, replace `-m pytest` with a
# bootstrap that drops the root and inserts src/.
_PLANNED_TESTS_BOOTSTRAP = (
    "import importlib,os,sys;"
    "root=os.getcwd();"
    "src=os.path.join(root,'src');"
    "root_n=os.path.normcase(os.path.abspath(root));"
    "sys.path[:]=[p for p in sys.path "
    "if os.path.normcase(os.path.abspath(p if p else root))!=root_n];"
    "sys.path.insert(0, src if os.path.isdir(src) else root);"
    "[importlib.import_module(n) for n in "
    "(os.listdir(src) if os.path.isdir(src) else []) "
    "if os.path.isfile(os.path.join(src,n,'__init__.py'))];"
    "raise SystemExit(__import__('pytest').main(sys.argv[1:]))"
)


def _append_pytest_runtime_args(
    definition: str, resolved: list[str], repo_root: Path | None
) -> None:
    if definition != "pytest-planned-tests":
        return
    src_layout = repo_root is not None and (repo_root / "src").is_dir()
    if src_layout:
        try:
            module_flag_at = resolved.index("-m")
        except ValueError:
            module_flag_at = -1
        if (
            module_flag_at != -1
            and module_flag_at + 1 < len(resolved)
            and resolved[module_flag_at + 1] == "pytest"
        ):
            resolved[module_flag_at : module_flag_at + 2] = ["-c", _PLANNED_TESTS_BOOTSTRAP]
    if importlib.util.find_spec("pytest_asyncio") is not None:
        resolved.extend(["-p", "pytest_asyncio.plugin"])


def _resolve_command(
    check: CheckDefinition,
    changed_files: list[str],
    planned_tests: list[str] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    definition = check.definition
    if definition is None:
        raise ValueError(f"Check {check.id!r} has no local definition to run")
    template = CHECK_REGISTRY.get(definition)
    if template is None:
        raise ValueError(f"Unknown check definition: {definition!r}")
    resolved: list[str] = []
    for arg in template:
        if arg == "{planned_tests}":
            resolved.extend(planned_tests or [])
            continue
        resolved.append(arg.replace("{python}", sys.executable))
    _append_pytest_runtime_args(definition, resolved, repo_root)
    if check.append_changed_files:
        resolved.extend(changed_files)
    return resolved


def run_check(
    config: Config,
    check: CheckDefinition,
    changed_files: list[str],
    planned_tests: list[str] | None = None,
) -> CommandResult:
    if check.ci_only and check.definition is None:
        return CommandResult(
            check_id=check.id,
            command=[],
            exit_code=None,
            duration_seconds=0.0,
            status=Severity.CI_REQUIRED,
        )

    if check.definition == "pytest-planned-tests" and not planned_tests:
        return CommandResult(
            check_id=check.id,
            command=[],
            exit_code=None,
            duration_seconds=0.0,
            status=Severity.BLOCKING,
            output_excerpt="No planned test files to run. Re-plan with a test file, or apply the proposal first.",
        )

    command = _resolve_command(check, changed_files, planned_tests, repo_root=config.repo_root)
    missing_module = _unimportable_dash_m_module(command)
    if missing_module is not None:
        return CommandResult(
            check_id=check.id,
            command=command,
            exit_code=None,
            duration_seconds=0.0,
            status=Severity.CI_REQUIRED,
            output_excerpt=(
                f"The active interpreter cannot import {missing_module!r}, so "
                "this check cannot run locally. Install it into the environment "
                "that runs contrib-pilot, or set the check's tier to \"ci\" with "
                "ci_only = true."
            ),
        )

    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(
            command,
            cwd=config.repo_root,
            env=_sanitized_env(config.repo_root),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,  # own process group, for group-wide kill on timeout
        )
    except FileNotFoundError as exc:
        duration = time.monotonic() - start
        return CommandResult(
            check_id=check.id,
            command=command,
            exit_code=None,
            duration_seconds=duration,
            status=Severity.BLOCKING,
            output_excerpt=f"Command not found: {exc}",
        )

    try:
        output, _ = proc.communicate(timeout=check.timeout_seconds)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        output, _ = proc.communicate()
        timed_out = True
        exit_code = None
    duration = time.monotonic() - start

    status = Severity.BLOCKING if (timed_out or exit_code not in (0, None)) else Severity.PASSED
    return CommandResult(
        check_id=check.id,
        command=command,
        exit_code=exit_code,
        duration_seconds=duration,
        status=status,
        output_excerpt=output[:MAX_OUTPUT_BYTES],
        timed_out=timed_out,
    )


def deterministic_findings(config: Config, plan: ChangePlan, changed_files: list[str]) -> list[Finding]:
    """Boundary and plan/test-mapping checks that need no subprocess."""

    findings: list[Finding] = []

    for changed in changed_files:
        if not config.is_allowed_change_path(changed):
            findings.append(
                Finding(
                    rule_id="boundary.path-outside-allowlist",
                    severity=Severity.BLOCKING,
                    message=f"Changed path is outside the allowed change paths: {changed}",
                    path=Path(changed),
                    evidence="Path did not match any glob in [changes].allowed_paths.",
                    remediation="Revert the file, or update the plan and config.toml together.",
                )
            )

    if not plan.test_files:
        findings.append(
            Finding(
                rule_id="tests.no-tests-planned",
                severity=Severity.ADVISORY,
                message="The plan proposes no test files.",
                evidence="ChangePlan.test_files is empty.",
                remediation="Add a focused test, or record an explicit justification in the plan.",
            )
        )

    changed_contents: dict[str, str] = {}
    for changed in changed_files:
        resolved = config.repo_root / changed
        if resolved.is_file() and str(changed).replace("\\", "/").endswith(".py"):
            changed_contents[str(changed).replace("\\", "/")] = resolved.read_text(encoding="utf-8")

    neighbor_contents: dict[str, str] = {}
    for evidence in plan.sources:
        posix = str(evidence.path).replace("\\", "/")
        if not posix.endswith(".py"):
            continue
        resolved = config.repo_root / evidence.path
        if resolved.is_file():
            try:
                neighbor_contents[posix] = resolved.read_text(encoding="utf-8")
            except OSError:
                continue

    findings.extend(
        evaluate_conventions(
            applicable_rules=plan.applicable_rules,
            observed_imports=plan.observed_imports,
            first_party_prefixes=config.first_party_prefixes,
            changed_contents=changed_contents,
            neighbor_contents=neighbor_contents,
            implementation_files=plan.implementation_files,
        )
    )

    return findings


def validate(
    *, config: Config, plan: ChangePlan, tier: str, changed_files: list[str], base_commit: str
) -> ValidationReport:
    findings = deterministic_findings(config, plan, changed_files)
    planned_tests = [str(path).replace("\\", "/") for path in plan.test_files]
    command_results = [
        run_check(config, check, changed_files, planned_tests) for check in config.checks_for_tier(tier)
    ]

    input_hashes = dict(plan.base_file_hashes)
    return ValidationReport(
        tier=tier,
        base_commit=base_commit,
        input_file_hashes=input_hashes,
        findings=findings,
        command_results=command_results,
    )
