"""Render report.md / report.json from already-recorded evidence.

Never reruns validation and never invents missing evidence — unknown states
stay explicit (plan.MD "Share Lifecycle Evidence" / CUJ 5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from contrib_pilot.models import ChangePlan, ProposedChange, ReviewSummary, ValidationReport


@dataclass
class ReportInputs:
    plan: ChangePlan
    proposal: ProposedChange | None
    validation: ValidationReport | None
    review: ReviewSummary | None
    provider: str


def _validation_lines(validation: ValidationReport | None) -> list[str]:
    if validation is None:
        return ["_No validation has been run yet._"]
    lines = [f"Tier: `{validation.tier}` at `{validation.base_commit[:12]}`", ""]
    for result in validation.command_results:
        lines.append(f"- `{result.check_id}` — **{result.status.value}** ({result.duration_seconds:.1f}s)")
    for finding in validation.findings:
        lines.append(f"- [{finding.severity.value}] `{finding.rule_id}`: {finding.message}")
    return lines


def render_markdown(inputs: ReportInputs) -> str:
    plan = inputs.plan
    lines: list[str] = [
        "# Contribution Report",
        "",
        f"Provider: `{inputs.provider}` · Base commit: `{plan.base_commit[:12]}`",
        "",
        "## Shared facts",
        "",
        "Acceptance criteria:",
        "",
    ]
    for criterion in plan.acceptance_criteria:
        covered = inputs.review.acceptance_coverage.get(criterion.id) if inputs.review else None
        mark = "x" if covered else " "
        lines.append(f"- [{mark}] `{criterion.id}` {criterion.text}")

    lines += [
        "",
        f"Implementation files: {', '.join(str(p) for p in plan.implementation_files) or '_none_'}",
        f"Test files: {', '.join(str(p) for p in plan.test_files) or '_none_'}",
        "",
        "## Validation",
        "",
        *_validation_lines(inputs.validation),
        "",
        "## Engineering",
        "",
        f"- Assumptions: {', '.join(plan.assumptions) or 'none recorded'}",
        f"- Sources consulted: {len(plan.sources)}",
        f"- Convention rules: {', '.join(plan.applicable_rules) or 'none'}",
        f"- Observed imports: {', '.join(plan.observed_imports) or 'none'}",
        f"- Proposal summary: {inputs.proposal.summary if inputs.proposal else '_not yet proposed_'}",
        "",
        "## PM",
        "",
    ]
    coverage = inputs.review.acceptance_coverage if inputs.review else {}
    covered_count = sum(1 for v in coverage.values() if v)
    lines.append(f"- Acceptance coverage: {covered_count}/{len(coverage)} criteria")
    lines.append(
        f"- Scope: {', '.join(str(e.path) for e in inputs.review.scope_drift) or 'no drift detected'}"
        if inputs.review
        else "- Scope: _review not yet run_"
    )

    lines += ["", "## QA", ""]
    lines.append(f"- Planned tests: {', '.join(str(p) for p in plan.test_files) or 'none'}")
    if inputs.review:
        lines.append(
            f"- Advisory findings: {len(inputs.review.unresolved_advisory)}"
        )

    lines += ["", "## DevOps", ""]
    ci_only = plan.ci_only_checks or ["none recorded"]
    lines.append(f"- CI-only checks: {', '.join(ci_only)}")
    lines.append(
        f"- Validation staleness: {'stale' if (inputs.review and inputs.review.validation_stale) else 'fresh or not applicable'}"
    )

    lines += ["", "## Readiness", ""]
    if inputs.review is None:
        lines.append("_Review has not been run. Readiness is unknown._")
    elif inputs.review.ready:
        lines.append("**Ready** — no blocking findings, no scope drift, validation is fresh.")
    else:
        lines.append("**Not ready.** Remaining issues:")
        for item in inputs.review.unresolved_blocking:
            lines.append(f"- {item}")
        for entry in inputs.review.scope_drift:
            lines.append(f"- `{entry.path}` ({entry.reason})")

    return "\n".join(lines) + "\n"


def render_json(inputs: ReportInputs) -> str:
    payload = {
        "schema_version": "1",
        "provider": inputs.provider,
        "plan": json.loads(inputs.plan.model_dump_json()),
        "proposal": json.loads(inputs.proposal.model_dump_json()) if inputs.proposal else None,
        "validation": json.loads(inputs.validation.model_dump_json()) if inputs.validation else None,
        "review": json.loads(inputs.review.model_dump_json()) if inputs.review else None,
    }
    return json.dumps(payload, indent=2) + "\n"
