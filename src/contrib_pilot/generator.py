"""ChangePlan -> ProposedChange.

Never writes repository files itself — it only returns proposed content for
``patches.py`` to diff and, later, apply (plan.MD "Change Proposal and
Human Review Contract").
"""

from __future__ import annotations

from contrib_pilot.config import Config
from contrib_pilot.context import read_approved
from contrib_pilot.errors import BoundaryViolationError
from contrib_pilot.models import ChangePlan, ProposedChange
from contrib_pilot.providers import GenerationProvider, ProposalRequest


def build_proposal(
    *, config: Config, plan: ChangePlan, provider: GenerationProvider
) -> ProposedChange:
    source_contents: dict[str, str] = {}
    for evidence in plan.sources:
        try:
            source_contents[str(evidence.path)] = read_approved(config, str(evidence.path))
        except BoundaryViolationError:
            continue

    request = ProposalRequest(plan=plan, source_contents=source_contents)
    proposal = provider.create_proposal(request)
    return _revalidate(proposal, config, plan)


def _revalidate(proposal: ProposedChange, config: Config, plan: ChangePlan) -> ProposedChange:
    planned_paths = {str(p) for p in (*plan.implementation_files, *plan.test_files)}

    for proposed_file in proposal.files:
        path_str = str(proposed_file.path)
        if path_str not in planned_paths:
            raise BoundaryViolationError(
                f"Proposal includes a file outside the approved plan: {path_str}",
                remediation="Re-plan to include this file, or drop it from the proposal.",
            )
        config.resolve_change_path(path_str)  # raises BoundaryViolationError if disallowed

    if not proposal.files:
        raise BoundaryViolationError(
            "Proposal contains no files", remediation="Re-plan or supply a manual patch."
        )

    return proposal
