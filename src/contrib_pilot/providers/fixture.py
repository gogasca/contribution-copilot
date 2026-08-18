"""Deterministic, offline provider for the bundled demo.

Reads versioned expected output from ``demo/expected/`` instead of calling a
model. This demonstrates orchestration and controls, not live
code-generation quality (plan.MD "Provider contract").
"""

from __future__ import annotations

import json
from pathlib import Path

from contrib_pilot.errors import MissingContextError
from contrib_pilot.models import ChangePlan, ProposedChange, ProposedFile
from contrib_pilot.providers import PlanRequest, ProposalRequest


class FixtureProvider:
    name = "fixture"

    def __init__(self, expected_dir: Path) -> None:
        self.expected_dir = expected_dir

    def create_plan(self, request: PlanRequest) -> ChangePlan:
        plan_path = self.expected_dir / "plan.json"
        if not plan_path.is_file():
            raise MissingContextError(
                f"No fixture plan at {plan_path}",
                remediation="Run `contrib-pilot demo reset` to restore the bundled fixture.",
            )
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        data["base_commit"] = request.base_commit
        return ChangePlan.model_validate(data)

    def create_proposal(self, request: ProposalRequest) -> ProposedChange:
        files_dir = self.expected_dir / "proposed_files"
        if not files_dir.is_dir():
            raise MissingContextError(
                f"No fixture proposal at {files_dir}",
                remediation="Run `contrib-pilot demo reset` to restore the bundled fixture.",
            )

        proposed: list[ProposedFile] = []
        for planned in [*request.plan.implementation_files, *request.plan.test_files]:
            candidate = files_dir / planned
            if not candidate.is_file():
                continue
            is_new = str(planned) not in request.source_contents
            proposed.append(
                ProposedFile(
                    path=planned,
                    content=candidate.read_text(encoding="utf-8"),
                    is_new_file=is_new,
                )
            )

        summary_path = self.expected_dir / "summary.txt"
        summary = (
            summary_path.read_text(encoding="utf-8").strip()
            if summary_path.is_file()
            else "Fixture-provided change."
        )

        return ProposedChange(
            plan_hash="fixture",
            files=proposed,
            summary=summary,
        )
