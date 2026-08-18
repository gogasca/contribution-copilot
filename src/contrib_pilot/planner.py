"""Issue -> ChangePlan.

Assembles bounded evidence, delegates drafting to the selected provider, and
then deterministically rechecks every path and source the provider returned
— provider output is never trusted on its own (plan.MD "Generation Boundary
and Failure Behavior").
"""

from __future__ import annotations

import re
from pathlib import Path

from contrib_pilot.config import Config
from contrib_pilot.context import discover_sources, file_hash, read_approved
from contrib_pilot.errors import BoundaryViolationError, MissingContextError
from contrib_pilot.models import ChangePlan
from contrib_pilot.providers import GenerationProvider, PlanRequest

_CRITERION_LINE = re.compile(r"^\s*\d+\.\s+(.*\S)\s*$")


def parse_issue(issue_path: Path) -> tuple[str, list[str]]:
    """Split an issue.md into free text and a numbered acceptance-criteria list.

    Numbered lines (``1. ...``) are treated as acceptance criteria; this is
    intentionally simple and deterministic rather than an LLM-parsed
    structure, so a missing criteria list fails loudly instead of being
    silently inferred.
    """

    if not issue_path.is_file():
        raise MissingContextError(f"Issue file not found: {issue_path}")

    text = issue_path.read_text(encoding="utf-8")
    criteria = [
        match.group(1)
        for line in text.splitlines()
        if (match := _CRITERION_LINE.match(line))
    ]
    return text, criteria


def build_plan(
    *,
    config: Config,
    issue_path: Path,
    base_commit: str,
    provider: GenerationProvider,
    source_purposes: dict[str, str],
) -> ChangePlan:
    issue_text, criteria_hint = parse_issue(issue_path)
    if not criteria_hint:
        raise MissingContextError(
            f"No numbered acceptance criteria found in {issue_path}",
            remediation="Add a numbered list of acceptance criteria to the issue file.",
        )

    sources = discover_sources(config, source_purposes)
    source_contents = {
        str(evidence.path): read_approved(config, str(evidence.path)) for evidence in sources
    }

    request = PlanRequest(
        issue_text=issue_text,
        acceptance_criteria_hint=criteria_hint,
        sources=sources,
        source_contents=source_contents,
        base_commit=base_commit,
        allowed_paths=list(config.allowed_paths),
    )

    plan = provider.create_plan(request)
    return _revalidate(plan, config, issue_path, base_commit, sources)


def _revalidate(
    plan: ChangePlan,
    config: Config,
    issue_path: Path,
    base_commit: str,
    sources: list,
) -> ChangePlan:
    """Deterministically recheck everything the provider returned.

    This is the boundary re-assertion described in DESIGN.md's "Generation
    boundary": a plan is only trusted once every path it names has been
    independently validated by the engine.
    """

    for implementation_path in plan.implementation_files:
        config.resolve_change_path(str(implementation_path))
    for test_path in plan.test_files:
        config.resolve_change_path(str(test_path))
    for evidence in plan.sources:
        if not config.is_allowed_source(str(evidence.path)):
            raise BoundaryViolationError(
                f"Plan cites an out-of-boundary source: {evidence.path}",
                remediation="Regenerate the plan; sources must come from allowed_sources.",
            )

    if not plan.implementation_files and not plan.test_files:
        raise BoundaryViolationError(
            "Plan proposes no files at all", remediation="Re-plan with a narrower issue."
        )

    base_file_hashes = dict(plan.base_file_hashes)
    for implementation_path in [*plan.implementation_files, *plan.test_files]:
        resolved = config.repo_root / implementation_path
        if resolved.is_file():
            try:
                base_file_hashes[str(implementation_path)] = file_hash(
                    config, str(implementation_path)
                )
            except BoundaryViolationError:
                pass  # target file may be new and outside allowed_sources by design

    return plan.model_copy(
        update={
            "issue_path": issue_path,
            "base_commit": base_commit,
            "sources": sources,
            "base_file_hashes": base_file_hashes,
        }
    )
