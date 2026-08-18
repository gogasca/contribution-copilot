# Contribution Copilot — Technical Design

Implementation reference for the Python artifact. Business rationale lives in [plan.MD](plan.MD); critical journeys live in [CUJS.md](CUJS.md).

## Scope and stack

Python 3.12 · `typer` · `pydantic` · `rich` · `pytest` · standard-library `subprocess`, `hashlib`, `difflib`, `tomllib`, `tempfile`, and `pathlib`.

No shell command strings, GitPython, web service, daemon, database, or IDE extension. The MVP supports UTF-8 regular-text file creation and replacement only. Deletes, renames, binary files, symlinks, submodules, and file-mode changes are rejected.

The demo targets vLLM commit `e0e5a7fb2808504ba86c94f7b379e38496002fd0` and the representative task defined in `plan.MD`.

## Repository layout

```text
.
├── pyproject.toml
├── uv.lock
├── README.md
├── plan.MD
├── CUJS.md
├── DESIGN.md
├── .gitignore
├── .vscode/
│   └── tasks.json
├── demo/
│   ├── SOURCE.md
│   ├── issue.md
│   ├── fixture-manifest.json
│   ├── source/                  # immutable pinned upstream fixture
│   ├── expected/                # versioned fixture-provider outputs
│   └── workspace/               # resettable demo target
├── .contrib-pilot/
│   ├── config.toml              # checked-in project policy
│   ├── hooks/                   # checked-in hook entrypoints
│   └── runs/                    # ignored runtime artifacts
├── src/contrib_pilot/
│   ├── __init__.py
│   ├── cli.py                   # Typer adapters; no policy logic
│   ├── services.py              # application-service interfaces
│   ├── config.py
│   ├── boundaries.py
│   ├── context.py
│   ├── planner.py
│   ├── generator.py
│   ├── providers.py
│   ├── patches.py
│   ├── executor.py
│   ├── validation.py
│   ├── review.py
│   ├── reporting.py
│   ├── git.py
│   ├── commits.py
│   ├── hooks.py
│   ├── orchestrator.py
│   ├── artifacts.py
│   ├── diagnostics.py
│   ├── errors.py
│   └── models.py
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

`pyproject.toml` exposes the `contrib-pilot` entry point. `uv.lock` is committed. `.gitignore` excludes `.contrib-pilot/runs/` and generated demo-workspace artifacts without ignoring checked-in policy, hooks, source fixtures, or expected outputs.

## Layering

```text
Typer command ───────┐
IDE task ────────────┼──> application service ──> domain modules
Git hook entrypoint ─┤
E2E orchestrator ────┘
```

Adapters translate input/output only. `run` calls the same application services as individual commands; it never invokes Typer commands and does not implement a second workflow.

## Core enums and shared metadata

```python
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class FindingSeverity(StrEnum):
    ADVISORY = "advisory"
    BLOCKING = "blocking"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
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


class ArtifactMetadata(BaseModel):
    schema_version: str = "1"
    artifact_id: str
    run_id: str
    created_at: datetime
    tool_version: str
    provider_id: str | None = None
    input_hashes: dict[str, str] = Field(default_factory=dict)
    content_sha256: str
```

`content_sha256` is computed over canonical JSON excluding the `content_sha256` field itself. JSON serialization uses sorted keys, UTF-8, and stable separators.

## Repository and input snapshots

```python
class RepositorySnapshot(BaseModel):
    repository_root: Path
    base_commit: str
    staged_diff_sha256: str
    working_diff_sha256: str
    untracked_paths: list[Path] = Field(default_factory=list)
    target_file_hashes: dict[str, str] = Field(default_factory=dict)


class InputFingerprint(BaseModel):
    issue_sha256: str
    configuration_sha256: str
    instruction_hashes: dict[str, str] = Field(default_factory=dict)
    consulted_source_hashes: dict[str, str] = Field(default_factory=dict)
    target_file_hashes: dict[str, str] = Field(default_factory=dict)
    command_definition_sha256: str
    rule_version: str
    tool_version: str
    provider_output_sha256: str | None = None
```

At run creation, capture the repository snapshot before tool-authored source changes. Untracked paths are inventoried by normalized relative name without reading contents unless the path is separately approved context.

## Plan and source models

```python
class SourceEvidence(BaseModel):
    path: Path
    sha256: str
    purpose: str


class AcceptanceCriterion(BaseModel):
    id: str
    text: str
    planned_tests: list[str] = Field(default_factory=list)


class ChangePlan(BaseModel):
    issue_path: Path
    base_commit: str
    base_file_hashes: dict[str, str]
    acceptance_criteria: list[AcceptanceCriterion]
    implementation_files: list[Path]
    test_files: list[Path]
    sources: list[SourceEvidence]
    assumptions: list[str] = Field(default_factory=list)
    ci_only_checks: list[str] = Field(default_factory=list)


class PlanArtifact(BaseModel):
    metadata: ArtifactMetadata
    plan: ChangePlan
```

All paths stored in domain artifacts are normalized repository-relative POSIX paths. Absolute paths appear only in runtime execution records where necessary and are never accepted from a provider.

## Proposal and approval models

```python
class ProposedFile(BaseModel):
    path: Path
    operation: Literal["create", "replace"]
    base_sha256: str | None = None
    proposed_sha256: str
    content: str


class ProposedChange(BaseModel):
    plan_artifact_id: str
    files: list[ProposedFile]
    proposal_sha256: str


class ProposalArtifact(BaseModel):
    metadata: ArtifactMetadata
    proposal: ProposedChange
    unified_diff_path: Path


class ApprovalArtifact(BaseModel):
    metadata: ArtifactMetadata
    proposal_sha256: str
    base_fingerprint_sha256: str
    invocation_identity: str
    approved_at: datetime
```

`proposal_sha256` is computed from normalized paths, operation, base hash, proposed hash, and complete proposed content. The approved diff is a presentation of the proposal; proposal content is authoritative.

`invocation_identity` is the local OS user and invocation mode recorded for audit convenience. It is not cryptographic identity or authorization. `--yes` can replay an existing approval matching the exact run, proposal, base fingerprint, tool version, and schema version; it cannot create approval.

## Validation, review, and report models

```python
class Finding(BaseModel):
    rule_id: str
    severity: FindingSeverity
    message: str
    path: Path | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    evidence: str
    remediation: str


class CommandResult(BaseModel):
    check_id: str
    command_fingerprint: str
    executable: Path
    arguments: list[str]
    cwd: Path
    environment_names: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    exit_code: int | None = None
    timed_out: bool = False
    output_truncated: bool = False
    output_sha256: str
    output_artifact: Path
    status: CheckStatus


class ValidationArtifact(BaseModel):
    metadata: ArtifactMetadata
    tier: Literal["fast", "ci"]
    findings: list[Finding] = Field(default_factory=list)
    commands: list[CommandResult] = Field(default_factory=list)
    post_validation_file_hashes: dict[str, str] = Field(default_factory=dict)


class ReviewArtifact(BaseModel):
    metadata: ArtifactMetadata
    readiness: Literal["blocked", "review_ready", "review_ready_with_ci_handoff"]
    scope_drift: list[Path] = Field(default_factory=list)
    stale_dependencies: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class ReportArtifact(BaseModel):
    metadata: ArtifactMetadata
    review_artifact_id: str
    markdown_path: Path
    json_path: Path
```

A command status and a finding severity are separate. For example, a timed-out required check produces `CommandResult(status=TIMED_OUT)` and a blocking finding explaining remediation.

## Run state and attempt history

```python
class StageAttempt(BaseModel):
    stage: Stage
    started_at: datetime
    finished_at: datetime
    succeeded: bool
    artifact_id: str | None = None
    error_code: int | None = None
    message: str


class RunState(BaseModel):
    schema_version: str = "1"
    run_id: str
    stage: Stage = Stage.CREATED
    created_at: datetime
    repository_snapshot: RepositorySnapshot
    current_fingerprint_sha256: str
    artifact_ids: dict[str, str] = Field(default_factory=dict)
    attempts: list[StageAttempt] = Field(default_factory=list)
```

Failed attempts are immutable history, not states. A failure leaves the run at its last valid stage.

## State transitions

| Current | Action and condition | Next |
| --- | --- | --- |
| `created` | plan validates | `planned` |
| `planned` | proposal validates and diff is written | `proposed` |
| `proposed` | exact approval recorded | `approved` |
| `approved` | base recheck and patch application succeed | `applied` |
| `applied` | required checks pass and validation changes no source file | `validated` |
| `applied` | check fails without source mutation | remain `applied` |
| `applied` | validation changes a source file | `proposed` after a new proposal/diff is recorded; previous approval is stale |
| `validated` | review finds no blocker or unexplained drift | `reviewed` |
| `validated` | review finds blocker or drift | remain `validated` |
| `reviewed` | report renders from current evidence | `reported` |

No transition skips approval or validation. A stage is committed only after its artifact has been written and verified.

## Invalidation rules

Each artifact lists its direct input hashes. On `run --resume`, recompute dependencies before reuse.

| Changed input | Earliest invalidated stage |
| --- | --- |
| Issue | `planned` |
| Applicable instruction or consulted source | `planned` |
| Provider identity/output | `planned` or `proposed`, depending on output |
| Plan content | `proposed` |
| Target base file before apply | `proposed`; application blocked |
| Proposal content or base fingerprint | `approved` |
| Applied implementation/test file | `validated` |
| Validation rule, command definition, configuration, or tool version | `validated` |
| Validation evidence | `reviewed` |
| Review evidence | `reported` |

Invalidation moves `RunState.stage` to the last still-valid predecessor, retains stale artifacts for audit, and records the exact changed dependency. It never silently deletes history.

## Provider contracts

```python
class ProviderConfig(BaseModel):
    provider_id: str
    model_id: str | None = None
    timeout_seconds: int
    max_input_bytes: int
    max_output_bytes: int
    credential_environment_variable: str | None = None


class ContextItem(BaseModel):
    path: Path
    sha256: str
    purpose: str
    content: str


class PlanRequest(BaseModel):
    issue_content: str
    base_commit: str
    allowed_change_patterns: list[str]
    context: list[ContextItem]


class ProposalRequest(BaseModel):
    plan: ChangePlan
    context: list[ContextItem]
    current_file_contents: dict[str, str]


class GenerationProvider(Protocol):
    provider_id: str

    def create_plan(self, request: PlanRequest) -> ChangePlan: ...
    def create_proposal(self, request: ProposalRequest) -> ProposedChange: ...
```

Providers are selected explicitly with `--provider fixture|assistant`.

- `FixtureProvider` loads versioned expected plan/proposal objects whose input hashes must match the current fixture. It proves orchestration and control behavior, not live generation quality.
- `AssistantProvider` receives only serialized request objects. It has no repository path, filesystem tool, shell tool, or independent retrieval. Its concrete model/provider ID is configuration, recorded in artifact metadata.

Before provider invocation, enforce item and total byte limits. Credentials are read only for transport and never serialized into requests or artifacts. Validate output size, schema, path boundaries, source references, and proposal hashes. Permit at most one repair request containing the schema errors and previous structured output; never change provider silently.

The FixtureProvider is the first implementation gate. One configured AssistantProvider is the second gate. Missing credentials produce exit code `3` without falling back.

## Canonical boundary algorithm

All context, proposal, changed-file, diagnostic, and artifact-path validation uses one `BoundaryResolver`.

For repository paths:

1. Require a non-empty relative path; reject absolute paths and NUL bytes.
2. Parse using POSIX separators and reject `.` or `..` segments where ambiguity exists.
3. Join to the recorded repository root.
4. Resolve existing parents and reject any symlink for mutable targets. Read-only context symlinks are allowed only when the final resolved target remains inside the repository and policy explicitly permits symlinks.
5. Verify containment using resolved path components, not string prefixes.
6. Convert back to a normalized repository-relative POSIX path.
7. Match against configured allowlist patterns using one tested matcher.
8. Recheck containment, type, and relevant hashes immediately before read or replacement.

Artifact paths must resolve under `.contrib-pilot/runs/<run-id>/`. Demo reset targets must resolve under a marked `demo/workspace/`. Provider-returned paths never authorize additional reads.

## Patch creation and application

The generator returns complete proposed contents. `patches.py`:

1. Validates the complete proposal before any tracked write.
2. Rejects duplicate paths and unsupported operations/types.
3. Recomputes base hashes and proposal hash.
4. Generates `proposal.diff` for human review.
5. Confirms exact approval.
6. Snapshots every existing affected file under the run directory.
7. Writes each proposed file to a same-directory temporary file, flushes and closes it, then uses `os.replace`.
8. On failure, attempts restoration from snapshots and removes only newly created files from this attempt.
9. Records original error and rollback outcome.

This is best-effort rollback, not a multi-file atomic transaction. Unknown user files and unrelated changes are never removed or restored.

## Check registry and executor

Project configuration chooses reviewed check IDs; it cannot define arbitrary commands.

```toml
[[checks]]
id = "focused-tests"
definition = "focused-import-utils-tests"
tier = "fast"
timeout_seconds = 60

[[checks]]
id = "gpu-integration"
definition = "gpu-integration"
tier = "ci"
ci_only = true
```

```python
class CommandSpec(BaseModel):
    definition: str
    executable: Literal["python", "uv", "git"]
    arguments: tuple[str, ...]
    network_required: bool = False
    may_modify_files: bool = False


CHECK_DEFINITIONS = {
    "focused-import-utils-tests": CommandSpec(
        definition="focused-import-utils-tests",
        executable="python",
        arguments=("-m", "pytest", "tests/utils/test_import_utils.py", "-q"),
    ),
}
```

The fixture-manifest build step must confirm whether `tests/utils/test_import_utils.py` is extended or created before freezing this definition.

Executor rules:

- Resolve executable from the active environment and the allowlisted enum.
- Use `shell=False`, argument arrays, and repository-root `cwd`.
- Build child environment from allowed names only. Provider credentials, tokens, proxy variables, and unrelated secrets are omitted.
- Reject network-required checks unless explicitly opted in; they remain disabled in the offline demo.
- Enforce per-command and total timeouts, process-group termination, and output-byte limits.
- Boundary-check appended changed-file arguments.
- Capture combined bounded output to an artifact and hash it.
- Record every field required by `CommandResult`.

An explicit repository pre-commit check may have `may_modify_files=true`. Hash relevant files before and after execution. Any mutation prevents a successful validation transition, creates a new proposal/diff, and invalidates approval.

## Artifact persistence and concurrency

`artifacts.py` owns all runtime persistence.

- Write canonical JSON to a temporary file inside the run directory, flush/close it, then `os.replace` the destination.
- Verify schema and `content_sha256` on every read.
- Maintain one `run.json` pointer to current stage and artifact IDs; artifacts themselves are immutable and uniquely named.
- Acquire an exclusive per-run lock before resume or mutation. A second process fails clearly rather than waiting indefinitely.
- Lock metadata contains PID, host, start time, and command. A lock is stale only when its local PID is confirmed absent; otherwise require explicit operator action.
- Run IDs use timestamp plus cryptographically random suffix.
- A stage transition occurs only after artifact write/read verification.

No fsync durability guarantee is claimed for the MVP. Interrupted writes cannot replace a valid artifact because replacement occurs only after the temporary file is complete.

## Validation and diagnostics

- `--tier fast`: deterministic boundaries/rules plus focused tests. Repository formatting/pre-commit checks are explicit definitions, not part of the non-mutating Contribution Copilot Git hook.
- `--tier ci`: complete check plan; unavailable accelerator/distributed checks report `CI_REQUIRED`, never `PASSED`.
- Blocking findings or failed required checks return exit code `6`.
- Advisory-only and CI-required results return `0` but remain visible.

Human diagnostics use:

```text
path:line:column: severity RULE_ID: message
```

Missing locations are rendered without fabricated coordinates. JSON output serializes the full `Finding` model.

## Mutation classes

| Operation | Mutation | Required control |
| --- | --- | --- |
| `plan`, dry-run scaffold, review, report | Run-artifact writes only | Run lock and atomic artifact persistence |
| `scaffold --apply` | Tracked source create/replace | Exact diff review, approval, base recheck, snapshot/rollback |
| `init` | May create local config/artifact directories | Dry-run preview; refuse to replace existing policy |
| `hooks install/uninstall` | Local Git configuration | Show exact change, confirm, preserve ownership record |
| `demo reset` | Marked demo workspace only | Resolve/verify marker, preview, confirm, never broad Git reset |
| `validate` | Normally artifacts; configured project checks may modify source | Detect mutation and invalidate approval/validation |
| `commit prepare` | Run-artifact writes only | Never stage, commit, push, or sign |

## Git hooks

Checked-in entrypoints call `contrib-pilot hook <name>`.

- `hooks status` reports repository-local and global `core.hooksPath`, existing hook files, Python/CLI availability, and installation ownership.
- `hooks install` refuses to replace an existing hooks path silently. With confirmation, it configures the versioned directory or emits composition instructions.
- Record the previous value and installed value in local tool state. `uninstall` restores only a value still matching what this tool installed; otherwise it stops.
- Hooks are executable on supported Linux. Windows is unsupported in the MVP and reported by `doctor`.
- `pre-commit` reads staged path/content through Git, runs only read-only sub-second rules with a short timeout, and never invokes mutating repository formatting hooks.
- If Python or the CLI is unavailable, fail with an actionable setup message for blocking policy hooks; optional advisory hooks may fail open only when configuration explicitly says so.
- CI remains authoritative because local hooks can be bypassed.

## E2E orchestration

```text
created → planned → proposed → approved → applied → validated → reviewed → reported
```

`run issue.md` executes until completion or a required pause. `run --resume` validates the lock, artifacts, fingerprints, and current repository before reuse. `--stop-after` stops after a valid stage. `--non-interactive` cannot create approval.

The default E2E command never stages, commits, pushes, opens a PR, or deploys.

## CI behavior

```bash
uv run contrib-pilot validate \
  --tier ci \
  --base-ref "$CI_BASE_REF" \
  --non-interactive \
  --format json
```

CI computes changed files from base/head refs and does not require local run or approval state. It uploads validation JSON, bounded logs, and a report. Local approval fields are `not_applicable`. CI evidence supersedes local evidence only for the same commit and command fingerprint.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Completed with no blocking finding |
| `2` | Invalid input or configuration |
| `3` | Missing required context, provider, or provider credentials |
| `4` | Boundary or policy violation |
| `5` | Stale base, patch conflict, unsafe write prevented, or active run lock |
| `6` | Required validation failed |
| `7` | Internal or artifact-integrity error |

## CLI surface

```text
contrib-pilot doctor
contrib-pilot init [--dry-run]
contrib-pilot demo reset [--dry-run]
contrib-pilot plan issue.md --provider fixture|assistant
contrib-pilot scaffold --dry-run
contrib-pilot scaffold --apply
contrib-pilot validate --tier fast|ci
contrib-pilot review
contrib-pilot report
contrib-pilot run issue.md [--resume] [--provider ...] [--stop-after ...]
contrib-pilot hooks install|status|uninstall
contrib-pilot commit prepare
```

Only `scaffold --apply` mutates contribution source files. Other commands may write run artifacts, initialize local configuration, alter explicitly approved local Git hook configuration, or restore only the marked demo workspace as described above.

## Test strategy

Unit tests:

- Pydantic schemas, canonical JSON, and artifact hashes.
- Boundary normalization, traversal, containment, glob behavior, and symlinks.
- Repository/input fingerprints and invalidation mapping.
- Every valid and invalid state transition.
- Proposal hashing, duplicate paths, unsupported operations, base mismatch, and rollback outcomes.
- Check-ID resolution, environment filtering, timeout, process-group termination, output truncation, and network denial.
- Provider input limits, schema failure, one repair attempt, missing credentials, and no fallback.
- Diagnostics with complete and missing locations.
- Hook conflict, ownership-aware uninstall, staged-content behavior, and unavailable Python.

Integration tests:

- Fixture-provider issue-to-report happy path.
- Interrupt after proposal and resume without repeating valid work.
- Missing exact approval blocks apply and non-interactive resume.
- Dirty repository preserves and does not attribute pre-existing staged, unstaged, and untracked changes.
- User changes target after proposal; apply is rejected without overwrite.
- Validation command modifies a file; approval and downstream evidence become stale.
- Prohibited context and proposal paths fail before read/write.
- Corrupt artifact and active lock fail safely.
- CI mode runs without local run or approval state.
- `demo reset` affects only a correctly marked demo workspace.

Rehearsal gates:

1. `uv sync --frozen` and `doctor` succeed from documented prerequisites.
2. Offline fixture run completes and resets repeatably.
3. Assistant run either completes with the configured provider or fails clearly without fallback.
4. One run against a full checkout at the pinned vLLM commit records observed commands and CI-only limitations.

## Implementation order

1. Package skeleton, configuration, models, canonical serialization, and artifact store.
2. Boundary resolver and Git repository snapshot.
3. Fixture manifest, immutable source fixture, issue, and expected outputs.
4. FixtureProvider planning and proposal generation.
5. Diff review, approval, safe apply, rollback, and staleness.
6. Check registry, executor, findings, and focused fixture validation.
7. Review, report, and commit preparation.
8. Orchestrator, interruption, resume, and invalidation.
9. IDE tasks and diagnostics.
10. Hooks after the core path is stable.
11. AssistantProvider behind the tested provider contract.

Implementation may begin after the fixture-manifest step verifies the pinned source/test paths and hashes. No expected output should be frozen before that verification.
