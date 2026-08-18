"""Resumable run/resume orchestration over the public stage services.

``run`` calls the same application services as the individual CLI commands
— it implements no second workflow. It cannot skip patch review, approval,
or required validation, and it invalidates downstream stages when relevant
inputs change (CUJS.md CUJ 9).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from contrib_pilot import generator, patches, planner, reporting, review as review_mod, validation as validation_mod
from contrib_pilot.config import Config
from contrib_pilot.errors import StaleStateError
from contrib_pilot.git import base_commit, changed_paths
from contrib_pilot.models import (
    ApprovalRecord,
    ChangePlan,
    ProposedChange,
    ReviewSummary,
    RunState,
    Stage,
    ValidationReport,
)
from contrib_pilot.providers import GenerationProvider

ConfirmFn = Callable[[str], bool]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_dir(config: Config, run_id: str) -> Path:
    return config.working_directory / run_id


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def load_state(config: Config, run_id: str) -> RunState | None:
    state_path = _run_dir(config, run_id) / "run.json"
    if not state_path.is_file():
        return None
    return RunState.model_validate_json(state_path.read_text(encoding="utf-8"))


def _save_state(config: Config, state: RunState) -> None:
    _write_json(_run_dir(config, state.run_id) / "run.json", state.model_dump_json(indent=2))


@dataclass
class RunResult:
    state: RunState
    paused: bool
    reason: str | None = None
    next_action: str | None = None


def run(
    *,
    config: Config,
    issue_path: Path,
    provider: GenerationProvider,
    source_purposes: dict[str, str],
    confirm: ConfirmFn,
    run_id: str | None = None,
    non_interactive: bool = False,
    stop_after: str | None = None,
) -> RunResult:
    commit = base_commit(config.repo_root)
    issue_hash = _hash_text(issue_path.read_text(encoding="utf-8"))

    if run_id is not None:
        existing = load_state(config, run_id)
        if existing is not None and existing.issue_hash != issue_hash:
            existing = RunState(
                run_id=run_id, stage=Stage.CREATED, issue_hash=issue_hash, base_commit=commit
            )
    else:
        run_id = new_run_id()
        existing = None

    state = existing or RunState(
        run_id=run_id, stage=Stage.CREATED, issue_hash=issue_hash, base_commit=commit
    )
    run_dir = _run_dir(config, run_id)

    def _stop_here(stage: Stage) -> bool:
        return stop_after is not None and stage.value == stop_after

    # --- plan ---
    plan: ChangePlan
    if state.stage.value in ("created",):
        plan = planner.build_plan(
            config=config,
            issue_path=issue_path,
            base_commit=commit,
            provider=provider,
            source_purposes=source_purposes,
        )
        plan_path = run_dir / "plan.json"
        _write_json(plan_path, plan.model_dump_json(indent=2))
        state = state.model_copy(
            update={"stage": Stage.PLANNED, "artifact_paths": {**state.artifact_paths, "plan": str(plan_path)}}
        )
        _save_state(config, state)
    else:
        plan = ChangePlan.model_validate_json(Path(state.artifact_paths["plan"]).read_text())

    if _stop_here(Stage.PLANNED):
        return RunResult(state=state, paused=True, next_action="contrib-pilot scaffold --dry-run")

    # --- propose (dry-run) ---
    proposal: ProposedChange
    if state.stage is Stage.PLANNED:
        proposal = generator.build_proposal(config=config, plan=plan, provider=provider)
        diff_text = patches.render_unified_diff(config, proposal)
        proposal_path = run_dir / "proposal.json"
        diff_path = run_dir / "proposal.diff"
        _write_json(proposal_path, proposal.model_dump_json(indent=2))
        _write_json(diff_path, diff_text)
        state = state.model_copy(
            update={
                "stage": Stage.PROPOSED,
                "proposal_hash": patches.proposal_hash(proposal),
                "artifact_paths": {
                    **state.artifact_paths,
                    "proposal": str(proposal_path),
                    "diff": str(diff_path),
                },
            }
        )
        _save_state(config, state)
    else:
        proposal = ProposedChange.model_validate_json(Path(state.artifact_paths["proposal"]).read_text())

    if _stop_here(Stage.PROPOSED):
        return RunResult(state=state, paused=True, next_action="review proposal.diff, then re-run")

    # --- human approval + apply ---
    if state.stage is Stage.PROPOSED:
        if non_interactive:
            return RunResult(
                state=state,
                paused=True,
                reason="non_interactive requires a prior recorded approval",
                next_action="Approve interactively once, or supply --run-id of an approved run.",
            )
        approved = confirm(f"Apply proposal touching {len(proposal.files)} file(s)?")
        if not approved:
            return RunResult(state=state, paused=True, reason="not approved", next_action="Edit and re-run, or reject.")

        approval = ApprovalRecord(
            run_id=run_id,
            proposal_hash=state.proposal_hash or patches.proposal_hash(proposal),
            base_state_fingerprint=_hash_text(json.dumps(plan.base_file_hashes, sort_keys=True)),
            approver="local-user",
            timestamp=datetime.now(UTC).isoformat(),
            invocation_mode="interactive",
        )
        approval_path = run_dir / "approval.json"
        _write_json(approval_path, approval.model_dump_json(indent=2))

        try:
            apply_result = patches.apply_proposal(config, plan, proposal)
        except StaleStateError:
            return RunResult(state=state, paused=True, reason="stale base state", next_action="Re-plan.")

        state = state.model_copy(
            update={
                "stage": Stage.APPLIED,
                "approval_hash": _hash_text(approval.model_dump_json()),
                "artifact_paths": {**state.artifact_paths, "approval": str(approval_path)},
            }
        )
        _save_state(config, state)
        if apply_result.error:
            return RunResult(state=state, paused=True, reason=f"apply failed: {apply_result.error}")

    if _stop_here(Stage.APPLIED):
        return RunResult(state=state, paused=True, next_action="contrib-pilot validate --tier fast")

    # --- validate ---
    validation_report: ValidationReport
    if state.stage is Stage.APPLIED:
        changed = changed_paths(config.repo_root)
        validation_report = validation_mod.validate(
            config=config, plan=plan, tier="fast", changed_files=changed, base_commit=commit
        )
        validation_path = run_dir / "validation.json"
        _write_json(validation_path, validation_report.model_dump_json(indent=2))
        state = state.model_copy(
            update={
                "stage": Stage.VALIDATED,
                "validation_input_hash": _hash_text(json.dumps(validation_report.input_file_hashes, sort_keys=True)),
                "artifact_paths": {**state.artifact_paths, "validation": str(validation_path)},
            }
        )
        _save_state(config, state)
        if validation_report.has_blocking:
            return RunResult(state=state, paused=True, reason="blocking validation failure")
    else:
        validation_report = ValidationReport.model_validate_json(
            Path(state.artifact_paths["validation"]).read_text()
        )

    if _stop_here(Stage.VALIDATED):
        return RunResult(state=state, paused=True, next_action="contrib-pilot review")

    # --- review ---
    review_summary: ReviewSummary
    if state.stage is Stage.VALIDATED:
        changed = changed_paths(config.repo_root)
        review_summary = review_mod.build_review(
            plan=plan, changed_files=changed, validation=validation_report, current_base_commit=commit
        )
        review_path = run_dir / "review.json"
        _write_json(review_path, review_summary.model_dump_json(indent=2))
        state = state.model_copy(
            update={"stage": Stage.REVIEWED, "artifact_paths": {**state.artifact_paths, "review": str(review_path)}}
        )
        _save_state(config, state)
        if review_summary.scope_drift or review_summary.unresolved_blocking:
            return RunResult(state=state, paused=True, reason="scope drift or unresolved findings")
    else:
        review_summary = ReviewSummary.model_validate_json(Path(state.artifact_paths["review"]).read_text())

    if _stop_here(Stage.REVIEWED):
        return RunResult(state=state, paused=True, next_action="contrib-pilot report")

    # --- report ---
    if state.stage is Stage.REVIEWED:
        report_inputs = reporting.ReportInputs(
            plan=plan, proposal=proposal, validation=validation_report, review=review_summary, provider=provider.name
        )
        report_md_path = run_dir / "report.md"
        report_json_path = run_dir / "report.json"
        _write_json(report_md_path, reporting.render_markdown(report_inputs))
        _write_json(report_json_path, reporting.render_json(report_inputs))
        state = state.model_copy(
            update={
                "stage": Stage.REPORTED,
                "artifact_paths": {
                    **state.artifact_paths,
                    "report_md": str(report_md_path),
                    "report_json": str(report_json_path),
                },
            }
        )
        _save_state(config, state)

    return RunResult(state=state, paused=False)
