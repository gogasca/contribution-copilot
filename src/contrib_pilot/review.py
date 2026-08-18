"""Scope-drift and staleness detection.

Compares the approved plan against the current working-tree diff and the
last validation run. Never claims "ready" while a blocking finding remains;
never hides advisories once raised (plan.MD "Change Proposal and Human
Review Contract").
"""

from __future__ import annotations

from contrib_pilot.models import ChangePlan, ReviewSummary, ScopeDriftEntry, Severity, ValidationReport
from pathlib import Path


def build_review(
    *,
    plan: ChangePlan,
    changed_files: list[str],
    validation: ValidationReport | None,
    current_base_commit: str,
) -> ReviewSummary:
    planned_impl = {str(p) for p in plan.implementation_files}
    planned_tests = {str(p) for p in plan.test_files}
    planned = planned_impl | planned_tests

    drift: list[ScopeDriftEntry] = []
    for changed in changed_files:
        if changed not in planned:
            drift.append(ScopeDriftEntry(path=Path(changed), reason="unplanned_file"))

    touched_impl = bool(planned_impl & set(changed_files))
    touched_tests = bool(planned_tests & set(changed_files))
    if touched_impl and planned_tests and not touched_tests:
        drift.append(
            ScopeDriftEntry(
                path=next(iter(planned_tests)),  # type: ignore[arg-type]
                reason="missing_planned_test",
            )
        )

    unresolved_blocking: list[str] = []
    unresolved_advisory: list[str] = []
    validation_stale = validation is None or validation.base_commit != current_base_commit
    if validation is not None and not validation_stale:
        for finding in validation.findings:
            if finding.severity is Severity.BLOCKING:
                unresolved_blocking.append(finding.message)
            elif finding.severity is Severity.ADVISORY:
                unresolved_advisory.append(finding.message)
        for result in validation.command_results:
            if result.status is Severity.BLOCKING:
                unresolved_blocking.append(f"{result.check_id} failed")

    changed_set = set(changed_files)

    def _covered(criterion) -> bool:
        # planned_tests may be plain file paths or pytest node ids
        # ("file.py::Class::method") — compare on the file portion only.
        planned_test_files = {test.split("::", 1)[0] for test in criterion.planned_tests}
        return bool(planned_test_files & changed_set) or bool(planned_test_files & planned_tests)

    acceptance_coverage = {criterion.id: _covered(criterion) for criterion in plan.acceptance_criteria}

    remaining_decisions = list(plan.assumptions)
    if validation_stale:
        remaining_decisions.append("Validation evidence is stale or missing; re-run `validate`.")

    ready = not drift and not unresolved_blocking and not validation_stale

    return ReviewSummary(
        ready=ready,
        acceptance_coverage=acceptance_coverage,
        scope_drift=drift,
        unresolved_blocking=unresolved_blocking,
        unresolved_advisory=unresolved_advisory,
        validation_stale=validation_stale,
        remaining_decisions=remaining_decisions,
    )
