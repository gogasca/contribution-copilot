"""ChangePlan -> ProposedChange.

Never writes repository files itself — it only returns proposed content for
``patches.py`` to diff and, later, apply (plan.MD "Change Proposal and
Human Review Contract").
"""

from __future__ import annotations

from contrib_pilot.config import Config
from contrib_pilot.context import read_approved
from contrib_pilot.conventions import NO_NEW_THIRD_PARTY, assert_no_new_third_party
from contrib_pilot.errors import BoundaryViolationError
from contrib_pilot.models import ChangePlan, ProposedChange
from contrib_pilot.patches import apply_edits
from contrib_pilot.providers import GenerationProvider, ProposalRequest

# Existing files larger than this are proposed as unique search/replace
# hunks, not complete-file rewrites. New files always use complete content.
MAX_COMPLETE_REWRITE_BYTES = 40_000


def _posix(path: object) -> str:
    return str(path).replace("\\", "/")


def build_proposal(
    *, config: Config, plan: ChangePlan, provider: GenerationProvider
) -> ProposedChange:
    source_contents: dict[str, str] = {}
    for evidence in plan.sources:
        try:
            source_contents[_posix(evidence.path)] = read_approved(config, str(evidence.path))
        except BoundaryViolationError:
            continue

    planned = [_posix(p) for p in (*plan.implementation_files, *plan.test_files)]
    rewrite_paths: list[str] = []
    edit_paths: list[str] = []
    for path in planned:
        existing = source_contents.get(path)
        if existing is None:
            rewrite_paths.append(path)
            continue
        if len(existing.encode("utf-8")) > MAX_COMPLETE_REWRITE_BYTES:
            edit_paths.append(path)
        else:
            rewrite_paths.append(path)

    request = ProposalRequest(
        plan=plan,
        source_contents=source_contents,
        rewrite_paths=rewrite_paths,
        edit_paths=edit_paths,
        applicable_rules=list(plan.applicable_rules),
        observed_imports=list(plan.observed_imports),
        lint_checks=list(plan.lint_checks),
        lint_policy_summary=plan.lint_policy_summary,
    )
    proposal = provider.create_proposal(request)
    return _revalidate(proposal, config, plan, source_contents)


def _revalidate(
    proposal: ProposedChange,
    config: Config,
    plan: ChangePlan,
    source_contents: dict[str, str],
) -> ProposedChange:
    planned_paths = {_posix(p) for p in (*plan.implementation_files, *plan.test_files)}

    for proposed_file in proposal.files:
        path_str = _posix(proposed_file.path)
        if path_str not in planned_paths:
            raise BoundaryViolationError(
                f"Proposal includes a file outside the approved plan: {path_str}",
                remediation="Re-plan to include this file, or drop it from the proposal.",
            )
        config.resolve_change_path(path_str)
        if proposed_file.edits:
            current = source_contents.get(path_str)
            if current is None:
                raise BoundaryViolationError(
                    f"Edits proposed for a file that is not in approved context: {path_str}",
                    remediation="Add the file to allowed_sources, or emit complete content for a new file.",
                )
            apply_edits(current, proposed_file.edits)

    if not proposal.files:
        raise BoundaryViolationError(
            "Proposal contains no files", remediation="Re-plan or supply a manual patch."
        )

    if NO_NEW_THIRD_PARTY in plan.applicable_rules:
        proposed_texts: dict[str, str] = {}
        for proposed_file in proposal.files:
            path_str = _posix(proposed_file.path)
            if proposed_file.edits:
                current = source_contents.get(path_str, "")
                proposed_texts[path_str] = apply_edits(current, proposed_file.edits)
            else:
                proposed_texts[path_str] = proposed_file.content or ""
        assert_no_new_third_party(
            implementation_files=plan.implementation_files,
            proposed_texts=proposed_texts,
            observed_imports=plan.observed_imports,
            first_party_prefixes=config.first_party_prefixes,
        )

    return proposal
