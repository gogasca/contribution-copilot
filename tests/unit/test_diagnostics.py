from pathlib import Path

from contrib_pilot.diagnostics import to_compiler_format
from contrib_pilot.models import Finding, Severity


def test_compiler_format_line() -> None:
    findings = [
        Finding(
            rule_id="tests.no-tests-planned",
            severity=Severity.ADVISORY,
            message="No tests planned.",
            path=Path("pkg/a.py"),
            line=12,
            evidence="ChangePlan.test_files is empty.",
            remediation="Add a test.",
        )
    ]
    line = to_compiler_format(findings)
    assert line == "pkg/a.py:12:1: advisory: No tests planned."


def test_compiler_format_defaults_when_no_path() -> None:
    findings = [
        Finding(
            rule_id="plan.assumption",
            severity=Severity.BLOCKING,
            message="Plan proposes no files.",
            evidence="empty",
            remediation="Re-plan.",
        )
    ]
    line = to_compiler_format(findings)
    assert line == "<plan>:1:1: blocking: Plan proposes no files."
