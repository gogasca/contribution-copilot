"""Pydantic schemas shared across the engine.

Every artifact carries ``schema_version`` so the final-round extension can
evolve these deliberately (see plan.MD "Future Extension for the Final
Challenge").
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Severity(StrEnum):
    PASSED = "passed"
    ADVISORY = "advisory"
    BLOCKING = "blocking"
    CI_REQUIRED = "ci_required"


class Stage(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    REPORTED = "reported"


class SourceEvidence(BaseModel):
    path: Path
    sha256: str
    purpose: str


class AcceptanceCriterion(BaseModel):
    id: str
    text: str
    planned_tests: list[str] = Field(default_factory=list)


class ChangePlan(BaseModel):
    schema_version: str = "1"
    issue_path: Path
    base_commit: str
    base_file_hashes: dict[str, str]
    acceptance_criteria: list[AcceptanceCriterion]
    implementation_files: list[Path]
    test_files: list[Path]
    sources: list[SourceEvidence]
    assumptions: list[str] = Field(default_factory=list)
    ci_only_checks: list[str] = Field(default_factory=list)
    provider: str = "fixture"


class ProposedFile(BaseModel):
    """Complete UTF-8 contents for one regular text file.

    Deletes, renames, binaries, symlinks, and mode changes are out of scope
    for the MVP (see plan.MD "Run Integrity, Ownership, and Staleness").
    """

    path: Path
    content: str
    is_new_file: bool = False


class ProposedChange(BaseModel):
    schema_version: str = "1"
    plan_hash: str
    files: list[ProposedFile]
    summary: str


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    message: str
    path: Path | None = None
    line: int | None = None
    evidence: str
    remediation: str


class CommandResult(BaseModel):
    check_id: str
    command: list[str]
    exit_code: int | None
    duration_seconds: float
    status: Severity
    output_artifact: Path | None = None
    output_excerpt: str = ""
    timed_out: bool = False


class ValidationReport(BaseModel):
    schema_version: str = "1"
    tier: str
    base_commit: str
    input_file_hashes: dict[str, str]
    findings: list[Finding] = Field(default_factory=list)
    command_results: list[CommandResult] = Field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return any(f.severity is Severity.BLOCKING for f in self.findings) or any(
            r.status is Severity.BLOCKING for r in self.command_results
        )


class ApprovalRecord(BaseModel):
    schema_version: str = "1"
    run_id: str
    proposal_hash: str
    base_state_fingerprint: str
    approver: str
    timestamp: str
    invocation_mode: str  # "interactive" | "non_interactive_replay"


class ScopeDriftEntry(BaseModel):
    path: Path
    reason: str  # "unplanned_file" | "missing_planned_test" | "unexplained_behavior_change"


class ReviewSummary(BaseModel):
    schema_version: str = "1"
    ready: bool
    acceptance_coverage: dict[str, bool]
    scope_drift: list[ScopeDriftEntry] = Field(default_factory=list)
    unresolved_blocking: list[str] = Field(default_factory=list)
    unresolved_advisory: list[str] = Field(default_factory=list)
    validation_stale: bool = False
    remaining_decisions: list[str] = Field(default_factory=list)


class RunState(BaseModel):
    schema_version: str = "1"
    run_id: str
    stage: Stage
    issue_hash: str
    base_commit: str
    proposal_hash: str | None = None
    approval_hash: str | None = None
    validation_input_hash: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)
