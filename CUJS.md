# Contribution Copilot: Critical User Journeys and Python Implementation

## Purpose

These Critical User Journeys (CUJs) translate the technical-screen plan into behavior that can be implemented, demonstrated, and tested. The primary persona is a new engineer making a first contribution. Engineering reviewers, QA, PM, and DevOps consume the evidence produced by the same workflow.

The implementation should optimize CUJ 1 first. CUJs 2–6 make that flow safe and useful across the software lifecycle. CUJs 7–8 demonstrate IDE integration and maintainability without requiring an IDE extension or a live vLLM installation.

## CUJ Summary


| Priority | Journey                                  | User outcome                                                        | Primary command               |
| -------- | ---------------------------------------- | ------------------------------------------------------------------- | ----------------------------- |
| P0       | 1. Plan a first contribution             | Engineer receives a bounded, convention-aware plan                  | `contrib-pilot plan issue.md` |
| P0       | 2. Review and apply a proposed change    | Engineer sees and approves a patch before files change              | `contrib-pilot scaffold`      |
| P0       | 3. Validate before code review           | Engineer catches objective failures and advisory risks early        | `contrib-pilot validate`      |
| P0       | 4. Detect scope drift and prepare review | Engineer confirms the final diff still matches the plan             | `contrib-pilot review`        |
| P0       | 5. Share lifecycle evidence              | Multiple roles receive one traceable report                         | `contrib-pilot report`        |
| P0       | 9. Run the governed flow end to end      | Engineer completes all stages through a resumable orchestrator      | `contrib-pilot run issue.md`  |
| P1       | 6. Recover safely from a blocked action  | Engineer receives a clear failure and remediation without data loss | All mutating commands         |
| P1       | 7. Work from an IDE                      | Engineer runs the same workflow and reviews artifacts in an IDE     | IDE tasks invoking CLI        |
| P1       | 8. Receive optional Git-time feedback    | Engineer catches fast policy violations while committing            | Installed Git hooks           |




## Developer Quickstart: From Clone to PR

This walks CUJs 1–9 into one continuous developer workflow, covering both the tool-scaffolded and hand-edited paths.

```bash
git clone <repo>
contrib-pilot init                          # once per clone; validates config.toml, creates .contrib-pilot/runs/
git switch -c bugfix/12345-validation-message
contrib-pilot hooks install                 # optional, but do this early so pre-commit gives fast feedback automatically
u                # do this before editing anything
```

From there, two supported paths converge on the same validation and review commands.

**Path A — tool-scaffolded.** Let the engine propose the change (CUJ 2):

```bash
contrib-pilot scaffold --dry-run            # writes proposal.diff, no tracked files touched
# review proposal.diff in the IDE diff viewer
contrib-pilot scaffold --apply              # rechecks base hashes, requires confirmation, applies atomically
```

**Path B — hand-edited.** Edit and save files directly, using the plan as the boundary and convention guide. This is an explicitly supported fallback (see "Generation Boundary and Failure Behavior" in plan.MD): a user-authored patch is a valid input, not only an assistant-generated one.

Both paths converge:

```bash
contrib-pilot validate --tier fast          # run this in a loop while iterating; scoped and fast by design
contrib-pilot review                        # compares the current diff against the plan; surfaces scope drift
contrib-pilot report                        # shared evidence for Engineering, PM, QA, and DevOps
```

Git remains entirely manual — the tool never stages, commits, or pushes:

```bash
git add vllm/example_module/validation.py \
        tests/example_module/test_validation.py
git commit -s -m "[Bugfix] Improve validation error for empty model names"
git push -u origin bugfix/12345-validation-message
```



### Recommendations

1. Run `plan` before writing any code, even on the hand-edited path — it is the step that prevents scope drift later, not an optional extra.
2. Install hooks right after `init` so fast feedback happens automatically on `git commit`, independent of whether `validate` was run manually.
3. If a change deviates from the plan's proposed files, re-run `plan` or record a justification rather than letting `review` discover it unexplained.
4. Run `validate --tier fast` early and often; reserve `--tier ci` for immediately before `review`, since it reports the complete check plan including which checks are `ci_required`.
5. Treat `ci_required` findings as accurate, not as a gap to route around — it means the tool correctly identified a check it cannot verify locally.
6. Read advisory findings for their cited evidence even when a run is otherwise clean; they are never hidden once raised.



## CUJ 1: Plan a First Contribution



### User story

As a new engineer, I want to give the tool an issue and receive a focused implementation and test plan based only on approved repository context, so I do not need to read the entire codebase before starting.

### Preconditions

- The repository has been initialized with `contrib-pilot init`.
- Project configuration identifies allowed paths, approved source paths, validation commands, and the working directory.
- The issue includes a description and acceptance criteria.
- The demo fixture or pinned vLLM checkout is available locally.



### Happy path

1. The engineer runs `contrib-pilot plan issue.md`.
2. The tool validates the issue and project configuration.
3. It inventories only approved guidance, nearby source files, tests, and project configuration.
4. It records every consulted source and its content hash.
5. It creates a structured plan containing:
  - normalized acceptance criteria;
  - proposed implementation and test files;
  - applicable conventions;
  - acceptance-criterion-to-test mapping;
  - local and CI-only checks;
  - assumptions, risks, and unanswered questions.
6. The tool writes `plan.json` and a readable `plan.md` to its ignored working directory.
7. No implementation file changes.



### Failure and recovery

- Missing acceptance criteria: stop and list the missing information.
- Required contribution guidance cannot be found: stop rather than inventing conventions.
- Suggested file is outside the allowlist: reject the plan and identify the violated rule.
- Assistant/model unavailable: retain deterministic discovery output and allow the engineer to supply a conforming `plan.json` manually.



### Acceptance criteria

- Planning performs no writes outside the tool working directory.
- Every plan claim links to an approved consulted source or is labeled as an assumption.
- The output proposes at least one focused test or requires a written justification.
- Re-running with unchanged inputs produces the same discovery inventory and stable structured fields.



## CUJ 2: Review and Apply a Proposed Change



### User story

As an engineer, I want to review the exact proposed code and test changes before they are applied, so generated suggestions never overwrite or silently alter my work.

### Happy path

1. The engineer runs `contrib-pilot scaffold --dry-run`.
2. The tool loads the approved plan and verifies current file hashes against the plan's base state.
3. It produces a unified diff containing implementation and test changes.
4. It validates all proposed paths against the allowlist.
5. It writes `proposal.diff` and displays a summary of files and changed lines.
6. The engineer reviews the diff in the terminal or IDE.
7. The engineer runs `contrib-pilot scaffold --apply`.
8. The tool rechecks base hashes, shows the change summary, and requests explicit confirmation unless `--yes` is used in an already approved automation context.
9. The tool snapshots all affected files, applies validated regular-text-file replacements, and writes an approval record. If a later write fails, it attempts rollback and reports whether restoration succeeded.



### Failure and recovery

- A target file changed after planning: refuse to apply and instruct the user to re-plan or regenerate the proposal.
- Patch conflict: leave tracked files unchanged and preserve the diff for manual review.
- Proposed path violates policy: reject the entire proposal.
- Partial application error: attempt restoration from the temporary snapshot and report both the original failure and rollback result. Do not claim transactional atomicity.



### Acceptance criteria

- `--dry-run` never changes tracked files.
- The applied bytes correspond exactly to the reviewed diff.
- Existing uncommitted edits are never overwritten.
- Approval records include the proposal hash, base commit, timestamp, and invocation mode.



## CUJ 3: Validate Before Code Review



### User story

As an engineer, I want one command to run the checks appropriate for my change and clearly separate failures, advisories, and unavailable CI checks.

### Happy path

1. The engineer runs `contrib-pilot validate --tier fast`.
2. The tool determines changed files and maps them to configured checks.
3. It runs deterministic boundary, plan/test mapping, and selected anti-pattern checks.
4. It invokes narrow existing project commands, such as focused pytest and pre-commit checks.
5. It captures command, duration, exit code, and bounded output.
6. It classifies each result:
  - `blocking`: objective policy violation or required check failure;
  - `advisory`: heuristic concern requiring human judgment;
  - `ci_required`: applicable check unavailable locally;
  - `passed`: locally observed success.
7. It writes `validation.json` and prints IDE-compatible diagnostics.



### Full-tier variation

`contrib-pilot validate --tier ci` produces the complete check plan. It may run locally supported checks, but accelerator or unavailable checks remain `ci_required`; they are never reported as passed without evidence.

### Failure and recovery

- Validation command is missing: classify it as configuration/environment failure with the expected setup command.
- Test fails: report the exact command and concise failure output; do not retry behavioral failures automatically.
- Heuristic detects a weak assertion: mark it advisory and cite the evidence rather than blocking by default.
- Output is too large: preserve full output in an artifact and show a concise terminal summary.



### Acceptance criteria

- Every invoked command and result is recorded.
- Local success and CI-required status cannot be conflated.
- Exit status is nonzero for blocking findings and zero for advisory-only findings unless strict mode is explicitly enabled.
- Diagnostics support both JSON and `path:line:column: severity: message` formats.



## CUJ 4: Detect Scope Drift and Prepare Review



### User story

As an engineer or reviewer, I want to know whether the final working-tree change still matches the approved plan and acceptance criteria before requesting review.

### Happy path

1. The engineer runs `contrib-pilot review`.
2. The tool loads the approved plan, proposal, current Git diff, and validation evidence.
3. It compares planned and actual files.
4. It flags unrelated files, unexplained behavior changes, missing planned tests, unresolved blocking findings, and stale validation evidence.
5. It produces a review summary with acceptance-criteria coverage and remaining decisions.



### Acceptance criteria

- New files or changed paths absent from the plan are visible as scope drift.
- Validation is marked stale if relevant files changed after it ran.
- The review summary never claims “ready” while a blocking finding remains.
- Advisory findings remain visible even when the change is otherwise review-ready.



## CUJ 5: Share Lifecycle Evidence



### User story

As a contributor, I want one report that lets Engineering, PM, QA, and DevOps understand the same change without maintaining separate, inconsistent documents.

### Happy path

1. The engineer runs `contrib-pilot report`.
2. The tool assembles existing plan, approval, diff, review, and validation artifacts without rerunning checks implicitly.
3. It writes `report.md` and `report.json`.
4. The report contains shared facts plus role-specific sections:
  - Engineering: design, diff, conventions, commands, assumptions, sign-off/disclosure readiness, and risks.
  - PM: acceptance coverage, user impact, scope, and deferred work.
  - QA: test cases, edge cases, regression surface, manual tests, and missing hardware coverage.
  - DevOps: local evidence, CI-required checks, dependencies/configuration, rollout signals, and rollback considerations.
5. Every status links back to its source artifact.



### Acceptance criteria

- The report is generated from recorded evidence rather than unsupported prose.
- All roles see the same acceptance criteria and validation state.
- Unknown and not-run states remain explicit.
- Markdown is readable in a terminal, browser, or IDE preview.



## CUJ 6: Recover Safely From a Blocked Action



### User story

As an engineer, I want failures to preserve my work and explain the next safe action.

### Demonstrated failure

1. After the proposal is generated, modify a target file manually or add an out-of-scope path.
2. Run `contrib-pilot scaffold --apply` or `contrib-pilot review`.
3. The tool detects the changed base or boundary violation.
4. It makes no destructive changes and prints:
  - what condition failed;
  - the affected file or rule;
  - what evidence was expected and observed;
  - safe remediation commands.



### Acceptance criteria

- Failures do not delete, reset, or overwrite repository content.
- Temporary application state is cleaned up or retained with a clear recovery explanation.
- Error output is actionable and has a stable error code.



## CUJ 7: Work From an IDE



### User story

As an engineer working primarily in an IDE, I want to invoke and review the same workflow without learning a separate product experience.

### Happy path

1. The engineer opens the repository and `issue.md`.
2. They run an IDE task named “Contribution Copilot: Plan.”
3. The task invokes the Python CLI and opens or links to `plan.md`.
4. They run “Contribution Copilot: Propose Changes.”
5. The task generates `proposal.diff`, which opens in the IDE diff viewer.
6. They approve/apply through the CLI task, then run “Validate.”
7. Findings appear in the terminal and IDE Problems panel through a problem matcher.
8. They open `report.md` in Markdown preview.



### Acceptance criteria

- IDE tasks contain no policy or business logic.
- Terminal and IDE runs produce the same JSON artifacts for the same repository state.
- The core workflow remains usable in any editor.
- A sample `.vscode/tasks.json` may be included for the demo, but the Python package has no VS Code or Cursor dependency.



## CUJ 8: Receive Optional Git-Time Feedback



### User story

As an engineer, I want fast feedback during normal Git operations without allowing hooks to generate code, rewrite files, or replace an existing hook setup silently.

### Installation journey

1. The engineer runs `contrib-pilot hooks status`.
2. The tool reports the current `core.hooksPath`, detected hooks, and proposed installation.
3. The engineer runs `contrib-pilot hooks install`.
4. If no conflict exists, the tool configures the versioned hook directory after confirmation.
5. If another hook system exists, installation stops and provides composition instructions.



### Commit journey

1. The engineer stages files and runs `git commit`.
2. `pre-commit` invokes `contrib-pilot hook pre-commit`.
3. It checks staged paths, prohibited files, plan/test mapping, and only configured fast checks.
4. Objective failures block the commit with remediation; advisory findings are printed but do not block by default.
5. The hook does not modify files.



### Acceptance criteria

- Installation is explicit, inspectable, and reversible.
- Existing hooks or `core.hooksPath` are never replaced silently.
- Hook execution is offline, deterministic, and bounded by a short timeout.
- Hook checks examine staged content where relevant rather than unrelated working-tree changes.
- CI remains authoritative because Git hooks can be bypassed.



## CUJ 9: Run the Governed Flow End to End



### User story

As an engineer, I want one resumable command that carries the issue through planning, proposal review, validation, and reporting without weakening the human approval points.

### Command

```bash
contrib-pilot run issue.md
```

The command orchestrates the existing public stage commands rather than implementing a second workflow:

```text
init/check configuration
        |
        v
plan -------- needs input --------> pause with remediation
        |
        v
scaffold --dry-run
        |
        v
human reviews proposal.diff ------> reject/edit/re-plan
        |
        v
scaffold --apply (explicit approval)
        |
        v
validate --tier fast
        |
        +---- blocking failure ----> pause; preserve evidence
        |
        v
review
        |
        +---- scope drift ---------> pause; re-plan or justify
        |
        v
report
        |
        v
optional commit preparation
```



### Resumption and automation

- Persist a `run.json` state machine after every completed stage.
- Resume with `contrib-pilot run --resume` or a specific `--run-id`.
- Recheck input hashes before trusting a completed stage. If relevant files changed, invalidate the stage and all dependent stages.
- Support `--non-interactive` only when a previously recorded proposal approval exists. Missing approval causes a safe failure rather than implicit acceptance.
- Support `--stop-after plan|proposal|apply|validate|review|report` for IDE tasks and debugging.
- Print the next action whenever the flow pauses.



### Suggested state model

```python
from enum import StrEnum

from pydantic import BaseModel


class Stage(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    REPORTED = "reported"


class RunState(BaseModel):
    schema_version: str = "1"
    run_id: str
    stage: Stage
    issue_hash: str
    base_commit: str
    proposal_hash: str | None = None
    approval_hash: str | None = None
    validation_input_hash: str | None = None
    artifact_paths: dict[str, str]
```

Do not model the flow as a single large function. `run` should call the same application services as `plan`, `scaffold`, `validate`, `review`, and `report`, making individual stages independently testable and usable from an IDE.

### Acceptance criteria

- One command reaches `report` on the happy path.
- The orchestrator cannot skip patch review, approval, or required validation.
- An interrupted run resumes without repeating valid completed work.
- Changed inputs invalidate stale downstream evidence.
- No default E2E mode commits, pushes, opens a PR, or deploys.



## From Working Change to Commit and PR

A commit does not come from a PR. The engineer first commits reviewed changes to a branch, pushes that branch, and then opens a PR containing one or more commits. Contribution Copilot should prepare and verify this handoff; it should not silently perform it.

### Recommended branch and commit journey

```bash
git switch -c bugfix/12345-validation-message
contrib-pilot run issue.md
git diff --check
git status --short
git add vllm/example_module/validation.py \
        tests/example_module/test_validation.py
git diff --cached
git commit -s -m "[Bugfix] Improve validation error for empty model names"
git push -u origin bugfix/12345-validation-message
```

The user stages explicit paths rather than `git add .`. `git diff --cached` is the final human view of exactly what will enter the commit. If hooks are installed, `pre-commit` evaluates that staged snapshot.

The `-s` flag adds a Developer Certificate of Origin sign-off line using the contributor's configured Git identity. The tool may check for sign-off readiness and explain it, but it must not invent an identity or attest on the user's behalf.

### Example commit

```text
commit 7f3ad5e2c8f1...
Author: Ada Contributor <ada@example.com>
Date:   Tue Aug 18 14:10:00 2026 +0000

    [Bugfix] Improve validation error for empty model names

    Return a targeted error when the configured model name is empty and add
    positive and negative regression coverage for the validation path.

    Signed-off-by: Ada Contributor <ada@example.com>
```

The subject should follow the pinned repository's actual convention. If vLLM requires category prefixes on PR titles rather than commit subjects, configure and validate the PR title separately instead of assuming the same rule applies to both.

### Suggested commit preparation command

```bash
contrib-pilot commit prepare
```

This command remains non-mutating. It should:

- confirm the report is current and no blocking finding remains;
- show planned versus currently changed and staged files;
- warn if unplanned or unstaged relevant files exist;
- verify that staged content matches the reviewed change;
- suggest a commit subject and body in `commit-message.txt`;
- show the explicit `git add` and `git commit -s` commands;
- never stage or commit by default.

An optional `contrib-pilot commit create` could be considered later, but only with an explicit staged-diff preview and confirmation. It is unnecessary for the technical-screen MVP.

### Example PR package

After the commit is pushed, the contributor opens a PR with a title and body prepared from recorded evidence:

```markdown
Title: [Bugfix] Improve validation error for empty model names

## Summary

- Return a targeted error for an empty model name.
- Preserve the existing behavior for valid model names.
- Add positive and negative regression tests.

## Why

New contributors and users currently receive an indirect downstream failure.
The new validation makes the configuration error actionable at its source.

## Testing

- `python -m pytest tests/example_module/test_validation.py -q` — passed locally
- pre-commit on changed files — passed locally
- GPU integration suite — CI required; this change does not exercise GPU code

## Risk and rollback

- Risk is limited to model-name input validation.
- Rollback is a revert of this commit.

## Checklist

- [x] Acceptance criteria mapped to tests
- [x] Contributor reviewed the complete staged diff
- [x] DCO sign-off present
- [x] AI assistance disclosed according to repository policy
- [ ] Required CI checks passed

Closes #12345
```

`report` and an optional `pr prepare` command can generate this package. The PR description must distinguish observed local results from pending CI results. The contributor remains responsible for verifying the title, issue linkage, disclosure, and complete diff before publication.

### Commit and PR safety checks

- The commit contains only explicitly staged, reviewed files.
- The staged diff hash matches the snapshot assessed by the latest review, or the report is marked stale.
- The sign-off uses the contributor's Git identity and is never fabricated.
- No local success is claimed for a CI-only check.
- Generated reports and transient run artifacts are excluded from the commit unless deliberately part of the contribution.
- Push and PR creation remain outside the default E2E command.



## Suggested Python Implementation



### Technology choices

Use Python 3.12 with a deliberately small dependency surface:

- `typer` for the CLI and generated help.
- `pydantic` for configuration and artifact schemas.
- `PyYAML` only if YAML configuration is required; TOML can otherwise use `tomllib` from the standard library.
- `rich` for readable summaries and confirmation prompts.
- `pytest` for unit and integration tests.

Use the standard library for `subprocess`, hashing, paths, JSON, temporary directories, diffs, and timestamps. Avoid GitPython initially; invoking Git with argument arrays keeps behavior transparent and reduces dependencies.

If minimizing dependencies is more important than CLI polish, replace Typer and Rich with `argparse` and plain output. Do not build a web service, database, daemon, or IDE extension for the screen.

### Repository layout

```text
contribution-copilot/
├── pyproject.toml
├── README.md
├── src/contrib_pilot/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── errors.py
│   ├── orchestrator.py
│   ├── context.py
│   ├── planner.py
│   ├── generator.py
│   ├── patches.py
│   ├── validation.py
│   ├── review.py
│   ├── reporting.py
│   ├── git.py
│   ├── commits.py
│   ├── hooks.py
│   └── diagnostics.py
├── .contrib-pilot/
│   ├── config.toml
│   ├── hooks/
│   │   ├── pre-commit
│   │   ├── commit-msg
│   │   └── pre-push
│   └── fixtures/vllm-sample/
├── .vscode/tasks.json
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

Runtime artifacts should live under an ignored directory such as `.contrib-pilot/runs/<run-id>/`. If `.contrib-pilot/` contains checked-in configuration and hooks, ignore only its `runs/` subtree rather than the entire directory.

### Core data models

```python
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Severity(StrEnum):
    PASSED = "passed"
    ADVISORY = "advisory"
    BLOCKING = "blocking"
    CI_REQUIRED = "ci_required"


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


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    message: str
    path: Path | None = None
    line: int | None = None
    evidence: str
    remediation: str


class CommandResult(BaseModel):
    command: list[str]
    exit_code: int | None
    duration_seconds: float
    status: Severity
    output_artifact: Path
```

Artifacts should include a schema version so the final-round extension can evolve them deliberately.

### Module responsibilities

`config.py`

- Load `config.toml`.
- Resolve paths without allowing escape from the repository root.
- Validate allowed sources, allowed change paths, checks, timeouts, and artifact locations.

`context.py`

- Find applicable repository guidance and nearby examples.
- Enforce the source allowlist before every read.
- Hash and record consulted files.
- Return structured evidence rather than an unbounded prompt string.

`orchestrator.py`

- Execute the public stages through their shared application services.
- Persist and validate `RunState` after each completed stage.
- Resume valid work and invalidate downstream stages when inputs change.
- Pause at approval, blocking findings, and scope drift with a clear next action.

`planner.py`

- Parse issue input and acceptance criteria.
- Assemble approved evidence for the planning adapter.
- Validate assistant output against `ChangePlan`.
- Recheck every proposed path and source deterministically.

`generator.py`

- Accept an approved `ChangePlan` and return complete UTF-8 contents for the small allowlisted set of proposed regular text files. Structured edits, deletes, renames, binary files, symlinks, and mode changes are outside the MVP.
- Implement an explicitly selected `FixtureProvider` for deterministic offline runs and `AssistantProvider` for live bounded generation.
- Give providers approved content and metadata only, never repository paths or filesystem tools.
- Validate provider identity, schema, output size, paths, and references; allow at most one schema-repair attempt.
- Never write repository files.

`patches.py`

- Generate a unified diff from current and proposed content.
- Hash the proposal and base files.
- Apply only after rechecking hashes and approval.
- Use a temporary staging area and atomic replacement where possible.

`validation.py`

- Select checks from changed paths and configuration.
- Resolve versioned check IDs to checked-in executable/argument definitions; never execute commands from issue text, provider output, plans, or run artifacts.
- Invoke commands with argument arrays, `shell=False`, explicit working directory, allowlisted environment variables, captured bounded output, timeouts, and process-group termination.
- Implement deterministic policy rules separately from heuristic rules.
- Produce `Finding` and `CommandResult` records.

`review.py`

- Compare planned files, approved proposal, Git diff, and current file hashes.
- Detect scope drift and stale validation.
- Compute readiness without hiding advisories or unknown states.

`reporting.py`

- Render Markdown and JSON from existing artifacts.
- Avoid rerunning validation or inventing missing evidence.
- Keep shared facts canonical and derive each role view from them.

`git.py`

- Wrap a small allowlist of read-oriented Git commands.
- Pass commands as argument lists with `shell=False`.
- Support base commit, diff, staged paths, repository root, and `core.hooksPath` inspection.

`commits.py`

- Compare the staged diff with the last reviewed snapshot.
- Suggest a commit message from recorded evidence.
- Check sign-off readiness without inventing contributor identity.
- Produce commands and artifacts without staging, committing, or pushing.

`hooks.py`

- Inspect before installing.
- Configure hooks only after confirmation.
- Run fast checks against staged content.
- Provide uninstall that removes only configuration installed by this tool.



### Configuration sketch

```toml
schema_version = "1"
working_directory = ".contrib-pilot/runs"
max_changed_files = 6
max_changed_lines = 250

[context]
allowed_sources = [
  "AGENTS.md",
  "docs/**",
  "vllm/example_module/**",
  "tests/example_module/**",
  ".pre-commit-config.yaml",
  "pyproject.toml",
]

[changes]
allowed_paths = [
  "vllm/example_module/**",
  "tests/example_module/**",
]

[[checks]]
id = "focused-tests"
tier = "fast"
definition = "focused-import-utils-tests"
timeout_seconds = 60

[[checks]]
id = "pre-commit"
tier = "fast"
definition = "project-pre-commit-changed-files"
append_changed_files = true
timeout_seconds = 90

[[checks]]
id = "gpu-integration"
tier = "ci"
ci_only = true
```

Glob matching must be implemented consistently and tested, especially for repository-root containment and symlinks.

### CLI exit codes


| Code | Meaning                                               |
| ---- | ----------------------------------------------------- |
| `0`  | Completed; no blocking findings                       |
| `2`  | Invalid command input or configuration                |
| `3`  | Missing required context or generation provider       |
| `4`  | Boundary or policy violation                          |
| `5`  | Stale base, patch conflict, or unsafe write prevented |
| `6`  | Required validation failed                            |
| `7`  | Internal or artifact integrity error                  |


Advisory-only findings should return `0` by default. A documented `--strict` mode may promote configured advisories for CI.

### Implementation sequence

Build in vertical slices rather than completing every module independently:

1. **Fixture and models:** select the pinned example, create configuration and artifact schemas, and test boundary resolution.
2. **Read-only planning:** implement `init` and deterministic discovery; accept a hand-authored structured plan before integrating assistant generation.
3. **Patch review:** generate a fixture proposal, write `proposal.diff`, verify hashes, and apply it safely.
4. **Validation:** add one deterministic violation, one advisory heuristic, one focused test command, and one CI-required check.
5. **Review and report:** detect scope drift and render the four role sections from recorded artifacts.
6. **E2E orchestration:** add persisted stage state, safe resumption, and commit-message preparation.
7. **IDE adapters:** add JSON/compiler diagnostics and example tasks.
8. **Hooks:** install only after the core workflow is stable; reuse the fast validation functions.
9. **Assistant adapter:** add structured plan/proposal generation behind an interface, preserving manual fixture fallback.

This ordering produces a runnable artifact even if assistant integration or hooks take longer than expected.

## Suggested Demo Script

1. Reset the fixture.
2. Open `issue.md` and state the business goal and acceptance criteria.
3. Run the IDE “Plan” task or `contrib-pilot plan issue.md`.
4. Show the bounded consulted-source list and acceptance-to-test mapping.
5. Run `scaffold --dry-run` and inspect `proposal.diff` in the IDE.
6. Apply the approved patch.
7. Run fast validation and show a deliberately injected advisory or failure.
8. Correct it and rerun validation.
9. Run `review` and open `report.md`.
10. Demonstrate the controlled failure by changing a base file or attempting an out-of-scope path.
11. Optionally show `hooks status`; avoid spending demo time installing hooks unless asked.

The demo should emphasize that the value is the governed journey and shared evidence, not the quantity of generated code.