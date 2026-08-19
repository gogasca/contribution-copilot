from pathlib import Path

from contrib_pilot.models import AcceptanceCriterion, ChangePlan, Finding, Severity, ValidationReport
from contrib_pilot.review import build_review


def _plan() -> ChangePlan:
    return ChangePlan(
        issue_path=Path("issue.md"),
        base_commit="abc123",
        base_file_hashes={},
        acceptance_criteria=[AcceptanceCriterion(id="ac-1", text="works", planned_tests=["tests/t.py"])],
        implementation_files=[Path("pkg/a.py")],
        test_files=[Path("tests/t.py")],
        sources=[],
    )


def test_ready_when_no_drift_and_no_blocking() -> None:
    plan = _plan()
    validation = ValidationReport(tier="fast", base_commit="abc123", input_file_hashes={}, findings=[])
    summary = build_review(
        plan=plan,
        changed_files=["pkg/a.py", "tests/t.py"],
        validation=validation,
        current_base_commit="abc123",
    )
    assert summary.ready
    assert not summary.scope_drift


def test_unplanned_file_is_scope_drift() -> None:
    plan = _plan()
    summary = build_review(
        plan=plan,
        changed_files=["pkg/a.py", "tests/t.py", "pkg/unplanned.py"],
        validation=None,
        current_base_commit="abc123",
    )
    assert any(e.reason == "unplanned_file" for e in summary.scope_drift)
    assert not summary.ready


def test_blocking_finding_prevents_ready() -> None:
    plan = _plan()
    validation = ValidationReport(
        tier="fast",
        base_commit="abc123",
        input_file_hashes={},
        findings=[
            Finding(
                rule_id="x",
                severity=Severity.BLOCKING,
                message="bad",
                evidence="e",
                remediation="r",
            )
        ],
    )
    summary = build_review(
        plan=plan, changed_files=["pkg/a.py", "tests/t.py"], validation=validation, current_base_commit="abc123"
    )
    assert not summary.ready
    assert summary.unresolved_blocking


def test_advisory_finding_stays_visible_when_otherwise_ready() -> None:
    plan = _plan()
    validation = ValidationReport(
        tier="fast",
        base_commit="abc123",
        input_file_hashes={},
        findings=[
            Finding(rule_id="x", severity=Severity.ADVISORY, message="fyi", evidence="e", remediation="r")
        ],
    )
    summary = build_review(
        plan=plan, changed_files=["pkg/a.py", "tests/t.py"], validation=validation, current_base_commit="abc123"
    )
    assert summary.ready
    assert summary.unresolved_advisory == ["fyi"]


def test_backslash_changed_paths_match_planned_files() -> None:
    plan = _plan()
    validation = ValidationReport(tier="fast", base_commit="abc123", input_file_hashes={}, findings=[])
    summary = build_review(
        plan=plan,
        changed_files=[r"pkg\a.py", r"tests\t.py"],
        validation=validation,
        current_base_commit="abc123",
    )
    assert summary.ready
    assert not summary.scope_drift


def test_missing_planned_test_when_only_implementation_changed() -> None:
    plan = _plan()
    summary = build_review(
        plan=plan,
        changed_files=["pkg/a.py"],
        validation=None,
        current_base_commit="abc123",
    )
    assert any(e.reason == "missing_planned_test" for e in summary.scope_drift)
    assert not summary.ready


def test_missing_or_stale_validation_blocks_ready() -> None:
    plan = _plan()
    summary = build_review(
        plan=plan, changed_files=["pkg/a.py", "tests/t.py"], validation=None, current_base_commit="abc123"
    )
    assert not summary.ready
    assert summary.validation_stale
