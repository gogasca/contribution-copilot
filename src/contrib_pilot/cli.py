"""Typer CLI — a thin adapter. No policy logic lives here.

Every command below calls into the shared engine modules; the CLI's job is
argument parsing, output formatting, and exit codes (plan.MD "CLI mode").
"""

from __future__ import annotations

import functools
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown

from contrib_pilot import commits, demo as demo_mod, generator, hooks as hooks_mod, orchestrator
from contrib_pilot import patches, planner, reporting, review as review_mod, validation as validation_mod
from contrib_pilot.config import Config, init_repo, load_config
from contrib_pilot.conventions import CONVENTION_SOURCE_PURPOSES
from contrib_pilot.errors import ContribPilotError
from contrib_pilot.git import (
    base_commit,
    contribution_changed_paths,
    repo_root as git_repo_root,
    staged_paths,
)
from contrib_pilot.models import ChangePlan, ProposedChange, ReviewSummary, Severity, ValidationReport

app = typer.Typer(add_completion=False, help="Contribution Copilot")
hooks_app = typer.Typer(add_completion=False, help="Manage Git hooks")
app.add_typer(hooks_app, name="hooks")

console = Console()
err_console = Console(stderr=True)

CURRENT_RUN_ID = "current"


def _source_purposes(config: Config) -> dict[str, str]:
    """Use exact (non-glob) allowed_sources as the planner's context set."""

    purposes: dict[str, str] = {}
    for pattern in config.allowed_sources:
        if any(char in pattern for char in "*?["):
            continue
        posix = pattern.replace("\\", "/")
        purposes[pattern] = CONVENTION_SOURCE_PURPOSES.get(posix, "approved source")
    return purposes


def _resolve_repo(path: Path | None) -> Path:
    start = path or Path.cwd()
    try:
        return git_repo_root(start)
    except Exception:  # noqa: BLE001 - fall back to cwd outside a git repo (e.g. tests)
        return start.resolve()


def _load_config(repo: Path) -> Config:
    return load_config(repo)


def _select_provider(name: str, config: Config):
    if name == "fixture":
        from contrib_pilot.providers.fixture import FixtureProvider

        # config.repo_root is demo/workspace when running the bundled demo;
        # demo/expected/ is its sibling, not nested inside the workspace.
        expected_dir = config.repo_root.parent / "expected"
        if not expected_dir.is_dir():
            expected_dir = config.repo_root / "demo" / "expected"
        return FixtureProvider(expected_dir=expected_dir)
    if name == "assistant":
        from contrib_pilot.providers.assistant import AssistantProvider

        return AssistantProvider()
    raise typer.BadParameter(f"Unknown provider: {name!r}")


def _run_dir(config: Config) -> Path:
    return config.working_directory / CURRENT_RUN_ID


def _handle_errors(fn):
    @functools.wraps(fn)  # preserve the signature Typer introspects for CLI params
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ContribPilotError as exc:
            err_console.print(f"[bold red]Error:[/bold red] {exc.message}")
            if exc.remediation:
                err_console.print(f"[dim]{exc.remediation}[/dim]")
            raise typer.Exit(code=int(exc.exit_code)) from None

    return wrapper


@app.command()
@_handle_errors
def init(path: Path = typer.Option(None, "--path", help="Repository path (default: cwd)")) -> None:
    """Copy the example policy if missing, then create the ignored run directory."""

    repo = _resolve_repo(path)
    config, created = init_repo(repo)
    copied = " (from examples/config.toml)" if created else ""
    console.print(
        f"[green]OK[/green] {repo} initialized. Config: schema v{config.schema_version}{copied}."
    )


@app.command()
@_handle_errors
def plan(
    issue: Path = typer.Argument(..., help="Path to issue.md"),
    provider: str = typer.Option("fixture", "--provider"),
    format: str = typer.Option("human", "--format"),
) -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    prov = _select_provider(provider, config)
    commit = base_commit(repo)

    err_console.print(f"[dim]Generating plan with [bold]{provider}[/bold]…[/dim]")
    result = planner.build_plan(
        config=config,
        issue_path=issue,
        base_commit=commit,
        provider=prov,
        source_purposes=_source_purposes(config),
    )

    run_dir = _run_dir(config)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "plan.md").write_text(_plan_markdown(result), encoding="utf-8")

    if format == "json":
        console.print_json(result.model_dump_json())
    else:
        console.print(Markdown(_plan_markdown(result)))


def _plan_markdown(plan_obj: ChangePlan) -> str:
    ci_only_lines = [f"- {c}" for c in plan_obj.ci_only_checks] or ["- none recorded"]
    lines = [
        "# Plan",
        "",
        "## Acceptance criteria",
        "",
        *[f"- `{c.id}` {c.text}" for c in plan_obj.acceptance_criteria],
        "",
        "## Files",
        "",
        f"- Implementation: {', '.join(str(p) for p in plan_obj.implementation_files)}",
        f"- Tests: {', '.join(str(p) for p in plan_obj.test_files)}",
        "",
        "## Sources consulted",
        "",
        *[f"- `{s.path}` ({s.purpose}) sha256:{s.sha256[:12]}" for s in plan_obj.sources],
        "",
        "## Conventions",
        "",
        f"- Rules: {', '.join(plan_obj.applicable_rules) or 'none'}",
        f"- Observed imports: {', '.join(plan_obj.observed_imports) or 'none'}",
        f"- Lint checks: {', '.join(plan_obj.lint_checks) or 'none'}",
        f"- Lint policy: {plan_obj.lint_policy_summary or 'none'}",
        "",
        "## CI-only checks",
        "",
        *ci_only_lines,
    ]
    return "\n".join(lines) + "\n"


def _load_plan(config: Config) -> ChangePlan:
    path = _run_dir(config) / "plan.json"
    if not path.is_file():
        raise typer.BadParameter("No plan found. Run `contrib-pilot plan issue.md` first.")
    return ChangePlan.model_validate_json(path.read_text(encoding="utf-8"))


@app.command()
@_handle_errors
def scaffold(
    dry_run: bool = typer.Option(False, "--dry-run"),
    apply: bool = typer.Option(False, "--apply"),
    yes: bool = typer.Option(False, "--yes"),
    provider: str = typer.Option("fixture", "--provider"),
) -> None:
    if dry_run == apply:
        raise typer.BadParameter("Pass exactly one of --dry-run or --apply.")

    repo = _resolve_repo(None)
    config = _load_config(repo)
    plan_obj = _load_plan(config)
    run_dir = _run_dir(config)

    if dry_run:
        prov = _select_provider(provider, config)
        err_console.print(f"[dim]Generating proposal with [bold]{provider}[/bold]…[/dim]")
        proposal = generator.build_proposal(config=config, plan=plan_obj, provider=prov)
        diff_text = patches.render_unified_diff(config, proposal)
        (run_dir / "proposal.json").write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / "proposal.diff").write_text(diff_text, encoding="utf-8")
        hunk_count = sum(1 for proposed_file in proposal.files if proposed_file.edits)
        console.print(
            f"[green]OK[/green] proposal.diff written ({len(proposal.files)} file(s)"
            + (f", {hunk_count} via search/replace" if hunk_count else "")
            + ")."
        )
        console.print(diff_text or "[dim](no changes)[/dim]")
        return

    proposal_path = run_dir / "proposal.json"
    if not proposal_path.is_file():
        raise typer.BadParameter("No proposal found. Run `contrib-pilot scaffold --dry-run` first.")
    proposal = ProposedChange.model_validate_json(proposal_path.read_text(encoding="utf-8"))

    if not yes:
        confirmed = typer.confirm(f"Apply proposal touching {len(proposal.files)} file(s)?")
        if not confirmed:
            console.print("[yellow]Not applied.[/yellow]")
            raise typer.Exit(code=0)

    result = patches.apply_proposal(config, plan_obj, proposal)
    if result.error:
        err_console.print(f"[bold red]Apply failed:[/bold red] {result.error}")
        err_console.print(f"Rollback succeeded: {result.rollback_succeeded}")
        raise typer.Exit(code=5)
    console.print(f"[green]OK[/green] applied {len(result.applied_paths)} file(s).")


@app.command()
@_handle_errors
def validate(
    tier: str = typer.Option("fast", "--tier"),
    format: str = typer.Option("human", "--format"),
    base_ref: str = typer.Option(None, "--base-ref"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
) -> None:
    """Run checks (tests). Does not decide whether the diff matches the plan."""
    repo = _resolve_repo(None)
    config = _load_config(repo)
    plan_obj = _load_plan(config)
    commit = base_ref or base_commit(repo)
    changed = contribution_changed_paths(repo, issue_path=plan_obj.issue_path)

    report = validation_mod.validate(
        config=config, plan=plan_obj, tier=tier, changed_files=changed, base_commit=commit
    )
    run_dir = _run_dir(config)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "validation.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")

    if format == "json":
        console.print_json(report.model_dump_json())
    elif format == "compiler":
        from contrib_pilot.diagnostics import to_compiler_format

        print(to_compiler_format(report.findings))
    else:
        for result in report.command_results:
            console.print(f"- {result.check_id}: [bold]{result.status.value}[/bold] ({result.duration_seconds:.1f}s)")
            if result.status is not Severity.PASSED and result.output_excerpt:
                console.print(result.output_excerpt.rstrip())
        for finding in report.findings:
            console.print(f"- [{finding.severity.value}] {finding.rule_id}: {finding.message}")

    if report.has_blocking:
        raise typer.Exit(code=6)


@app.command()
@_handle_errors
def review() -> None:
    """Check that the current diff still matches the plan. Does not re-run tests."""
    repo = _resolve_repo(None)
    config = _load_config(repo)
    plan_obj = _load_plan(config)
    run_dir = _run_dir(config)

    validation_path = run_dir / "validation.json"
    validation_report: ValidationReport | None = (
        ValidationReport.model_validate_json(validation_path.read_text(encoding="utf-8"))
        if validation_path.is_file()
        else None
    )

    commit = base_commit(repo)
    changed = contribution_changed_paths(repo, issue_path=plan_obj.issue_path)
    summary = review_mod.build_review(
        plan=plan_obj, changed_files=changed, validation=validation_report, current_base_commit=commit
    )
    (run_dir / "review.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")

    _DRIFT_LABEL = {
        "unplanned_file": "changed, but not in the plan",
        "missing_planned_test": "planned test file was not changed",
    }
    console.print("[dim]Review asks: does this diff still match the plan?[/dim]")
    console.print(f"Ready: [bold]{summary.ready}[/bold]")
    if not summary.scope_drift:
        console.print("- plan match: all changed files are in the plan")
    for entry in summary.scope_drift:
        label = _DRIFT_LABEL.get(entry.reason, entry.reason)
        console.print(f"- drift: `{entry.path}` ({label})")
    if summary.validation_stale:
        console.print("- validation: stale or missing — re-run `validate`")
    elif validation_report is not None:
        console.print("- validation: fresh (not re-run; using last validate result)")
    for item in summary.unresolved_blocking:
        console.print(f"- blocking: {item}")
    for item in summary.unresolved_advisory:
        console.print(f"- advisory: {item}")

    if not summary.ready:
        raise typer.Exit(code=4 if summary.scope_drift else 6)


@app.command()
@_handle_errors
def report(provider: str = typer.Option("fixture", "--provider")) -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    plan_obj = _load_plan(config)
    run_dir = _run_dir(config)

    def _maybe(name: str, cls):
        path = run_dir / name
        return cls.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    proposal = _maybe("proposal.json", ProposedChange)
    validation_report = _maybe("validation.json", ValidationReport)
    review_summary = _maybe("review.json", ReviewSummary)

    inputs = reporting.ReportInputs(
        plan=plan_obj, proposal=proposal, validation=validation_report, review=review_summary, provider=provider
    )
    md = reporting.render_markdown(inputs)
    js = reporting.render_json(inputs)
    (run_dir / "report.md").write_text(md, encoding="utf-8")
    (run_dir / "report.json").write_text(js, encoding="utf-8")
    console.print(Markdown(md))


@app.command(name="run")
@_handle_errors
def run_cmd(
    issue: Path = typer.Argument(..., help="Path to issue.md"),
    provider: str = typer.Option("fixture", "--provider"),
    resume: bool = typer.Option(False, "--resume"),
    run_id: str = typer.Option(None, "--run-id"),
    stop_after: str = typer.Option(None, "--stop-after"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
) -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    prov = _select_provider(provider, config)

    # Default to the same "current" slot plan/scaffold/validate/review/report
    # use, so `--resume` naturally continues the last run without requiring
    # the caller to remember a generated run id. Pass --run-id explicitly to
    # track multiple named runs in parallel.
    effective_run_id = run_id or CURRENT_RUN_ID

    def _confirm(message: str) -> bool:
        return typer.confirm(message)

    result = orchestrator.run(
        config=config,
        issue_path=issue,
        provider=prov,
        source_purposes=_source_purposes(config),
        confirm=_confirm,
        run_id=effective_run_id,
        non_interactive=non_interactive,
        stop_after=stop_after,
    )

    console.print(f"Run [bold]{result.state.run_id}[/bold] at stage [bold]{result.state.stage.value}[/bold]")
    if result.paused:
        console.print(f"[yellow]Paused[/yellow]: {result.reason or 'stop-after reached'}")
        if result.next_action:
            console.print(f"Next: {result.next_action}")
        raise typer.Exit(code=0)
    console.print("[green]Report complete.[/green]")


@hooks_app.command("status")
@_handle_errors
def hooks_status() -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    s = hooks_mod.status(config)
    console.print(f"core.hooksPath = {s.current_hooks_path!r}")
    console.print(f"managed by contrib-pilot: {s.managed}")
    console.print(f"would install at: {s.would_install_at}")


@hooks_app.command("install")
@_handle_errors
def hooks_install(yes: bool = typer.Option(False, "--yes")) -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    if not yes:
        yes = typer.confirm(f"Set core.hooksPath to {hooks_mod.MANAGED_HOOKS_DIR}?")
    s = hooks_mod.install(config, confirmed=yes)
    console.print(f"[green]OK[/green] core.hooksPath = {s.current_hooks_path}")


@hooks_app.command("uninstall")
@_handle_errors
def hooks_uninstall() -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    s = hooks_mod.uninstall(config)
    console.print(f"core.hooksPath = {s.current_hooks_path!r}")


@app.command(name="hook")
@_handle_errors
def hook_entrypoint(name: str = typer.Argument(..., help="pre-commit | commit-msg | pre-push")) -> None:
    """Invoked by the installed Git hook scripts, not by a human directly."""

    repo = _resolve_repo(None)
    config = _load_config(repo)

    if name == "pre-commit":
        staged = staged_paths(repo)
        findings = hooks_mod.staged_content_findings(config, staged)
        for finding in findings:
            console.print(f"[{finding.severity.value}] {finding.rule_id}: {finding.message}")
        if any(f.severity.value == "blocking" for f in findings):
            raise typer.Exit(code=4)
        return

    console.print(f"(no fast checks configured for {name})")


commit_app = typer.Typer(add_completion=False, help="Prepare (never perform) a commit")
app.add_typer(commit_app, name="commit")


@commit_app.command("prepare")
@_handle_errors
def commit_prepare() -> None:
    repo = _resolve_repo(None)
    config = _load_config(repo)
    plan_obj = _load_plan(config)

    readiness = commits.check_sign_off_readiness(repo)
    planned = [str(p) for p in (*plan_obj.implementation_files, *plan_obj.test_files)]
    diff_status = commits.planned_vs_staged(repo=repo, planned_paths=planned)

    message = commits.suggest_commit_message(
        subject_prefix="[Bugfix]",
        summary=plan_obj.acceptance_criteria[0].text if plan_obj.acceptance_criteria else "Update implementation",
        criteria_summary=[c.text for c in plan_obj.acceptance_criteria],
    )
    message_path = _run_dir(config) / "commit-message.txt"
    message_path.write_text(message, encoding="utf-8")

    console.print(f"Sign-off ready: {readiness.ready} ({readiness.name} <{readiness.email}>)")
    console.print(f"Staged & planned: {diff_status['staged_and_planned']}")
    console.print(f"Staged, not planned: {diff_status['staged_not_planned']}")
    console.print(f"Planned, not staged: {diff_status['planned_not_staged']}")
    console.print(f"Suggested message written to {message_path}")
    console.print(f"git add {' '.join(planned)}")
    console.print('git commit -s -F "%s"' % message_path)


demo_app = typer.Typer(add_completion=False, help="Manage the offline demo fixture")
app.add_typer(demo_app, name="demo")


@demo_app.command("reset")
@_handle_errors
def demo_reset() -> None:
    repo = demo_mod.docs_repo_root(Path.cwd())
    preview = demo_mod.reset(repo / "demo")
    console.print(f"[green]OK[/green] reset {len(preview.changed_files)} file(s) under {preview.target}")


@app.command()
@_handle_errors
def doctor() -> None:
    """Check setup. Safe to run from the repo root or from demo/workspace."""

    repo = demo_mod.docs_repo_root(Path.cwd())
    checks = demo_mod.run_doctor(repo)
    all_ok = True
    for check in checks:
        mark = "[green]OK[/green]" if check.ok else "[red]FAIL[/red]"
        console.print(f"{mark} {check.name}: {check.detail}")
        all_ok = all_ok and check.ok
    if not all_ok:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
