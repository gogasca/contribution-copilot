"""Generation provider protocol.

A provider only ever receives a bounded request assembled by the engine
(``PlanRequest`` / ``ProposalRequest``) — never a repository path or
filesystem/tool access. All provider output is untrusted input: callers must
re-validate it against the target schema before use (plan.MD "Generation
Boundary and Failure Behavior").
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from contrib_pilot.models import AcceptanceCriterion, ChangePlan, ProposedChange, SourceEvidence


class PlanRequest(BaseModel):
    issue_text: str
    acceptance_criteria_hint: list[str] = Field(default_factory=list)
    sources: list[SourceEvidence]
    source_contents: dict[str, str]
    base_commit: str
    allowed_paths: list[str]
    applicable_rules: list[str] = Field(default_factory=list)
    observed_imports: list[str] = Field(default_factory=list)
    lint_checks: list[str] = Field(default_factory=list)
    lint_policy_summary: str = ""


class ProposalRequest(BaseModel):
    plan: ChangePlan
    source_contents: dict[str, str]
    rewrite_paths: list[str] = Field(default_factory=list)
    edit_paths: list[str] = Field(default_factory=list)
    applicable_rules: list[str] = Field(default_factory=list)
    observed_imports: list[str] = Field(default_factory=list)
    lint_checks: list[str] = Field(default_factory=list)
    lint_policy_summary: str = ""


class GenerationProvider(Protocol):
    name: str

    def create_plan(self, request: PlanRequest) -> ChangePlan: ...

    def create_proposal(self, request: ProposalRequest) -> ProposedChange: ...


__all__ = [
    "AcceptanceCriterion",
    "GenerationProvider",
    "PlanRequest",
    "ProposalRequest",
]
