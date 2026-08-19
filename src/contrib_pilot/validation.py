"""Check selection, safe execution, and classification.

Commands run as argument arrays with ``shell=False``, an explicit working
directory, an allowlisted environment, and per-command/total timeouts
(plan.MD "Safe Command Execution"). ``CHECK_REGISTRY`` is the one place a
check id resolves to an executable — config.toml can only reference a
registry key, never raw command text.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from contrib_pilot.config import CheckDefinition, Config
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
    # Generic default for examples/config.toml. Teams should replace this
    # with a focused node-id command (see focused-import-utils-tests).
    "pytest-fast": [
        "{python}",
        "-m",
        "pytest",
        "-q",
    ],
}


def _sanitized_env() -> dict[str, str]:
    allowed = {key.upper() for key in _ALLOWED_ENV_KEYS}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    # Keep pytest from auto-loading third-party plugins (e.g. anyio) that are
    # installed into this interpreter but are unrelated to the focused tests.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _resolve_command(check: CheckDefinition, changed_files: list[str]) -> list[str]:
    if check.definition is None:
        raise ValueError(f"Check {check.id!r} has no local definition to run")
    template = CHECK_REGISTRY.get(check.definition)
    if template is None:
        raise ValueError(f"Unknown check definition: {check.definition!r}")
    resolved = [arg.replace("{python}", sys.executable) for arg in template]
    if check.append_changed_files:
        resolved.extend(changed_files)
    return resolved


def run_check(config: Config, check: CheckDefinition, changed_files: list[str]) -> CommandResult:
    if check.ci_only and check.definition is None:
        return CommandResult(
            check_id=check.id,
            command=[],
            exit_code=None,
            duration_seconds=0.0,
            status=Severity.CI_REQUIRED,
        )

    command = _resolve_command(check, changed_files)
    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(
            command,
            cwd=config.repo_root,
            env=_sanitized_env(),
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

    planned = {str(p) for p in (*plan.implementation_files, *plan.test_files)}
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

    return findings


def validate(
    *, config: Config, plan: ChangePlan, tier: str, changed_files: list[str], base_commit: str
) -> ValidationReport:
    findings = deterministic_findings(config, plan, changed_files)
    command_results = [
        run_check(config, check, changed_files) for check in config.checks_for_tier(tier)
    ]

    input_hashes = dict(plan.base_file_hashes)
    return ValidationReport(
        tier=tier,
        base_commit=base_commit,
        input_file_hashes=input_hashes,
        findings=findings,
        command_results=command_results,
    )
