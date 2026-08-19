# Solutions Architect Technical Screen Plan

## Objective

Build a runnable, repository-local Contribution Copilot that helps a new engineer produce one convention-compliant, review-ready contribution to a large open-source library without first understanding the entire codebase.

Use `vllm-project/vllm` as the stand-in for the customer's private, convention-heavy library. The demo is pinned to commit [`e0e5a7fb2808504ba86c94f7b379e38496002fd0`](https://github.com/vllm-project/vllm/commit/e0e5a7fb2808504ba86c94f7b379e38496002fd0), retrieved on 2026-08-18. The artifact will guide one scoped task through planning, design, implementation, testing, review preparation, CI handoff, and deployment readiness while producing useful evidence for Engineering, PM, QA, and DevOps.

The technical-screen deliverable is one polished contribution flow. Multi-issue campaign orchestration is a future extension for the final-round account scenario, not part of this implementation.

## Business Priority and Success Measures

The highest-value problem is reducing the time and senior-engineer support required for a new contributor to create a correct first change.

Expected impact:

- Lower time from issue intake to a review-ready change.
- Fewer convention-related review comments.
- Fewer avoidable test and validation cycles.
- More predictable handoff to QA and CI/deployment workflows.
- A shared evidence package that reduces repeated explanations across roles.

The demo will record concrete proxies rather than claim production impact from one run:

- Elapsed time from issue intake to review-ready report.
- Number and type of convention, boundary, and test findings caught before review.
- Acceptance criteria mapped to implementation and tests.
- Manual decisions and approvals required.
- Locally executed checks versus checks explicitly deferred to CI.

The first version will not attempt unrestricted autonomous development, unattended commits or PR submission, kernel changes, model enablement, automatic deployment, or orchestration across many issues.

## Pinned Demo Definition

Repository:

- URL: `https://github.com/vllm-project/vllm`
- Commit: `e0e5a7fb2808504ba86c94f7b379e38496002fd0`
- Retrieval date: 2026-08-18
- License: Apache-2.0; preserve upstream SPDX and attribution in fixture files.

Representative customer task:

> Improve `resolve_obj_by_qualname` so malformed values without a module/object separator fail with an actionable error, while valid qualified names and existing missing-attribute behavior remain unchanged.

This is a technical-screen scenario grounded in code at the pinned revision, not a claim that vLLM maintainers have accepted or requested this upstream change.

Acceptance criteria:

1. Empty strings and names without `.` raise `ValueError` with guidance that a fully qualified `module.attribute` name is required.
2. A valid standard-library qualified name still resolves successfully.
3. A valid module with a missing object continues to raise `AttributeError` rather than being reclassified as malformed input.
4. Focused positive and negative tests run without GPU or model access.

This task is intentionally hardware-agnostic, but not trivial: criterion 3 requires preserving vLLM's existing distinction between a malformed-input error (`ValueError`) and a missing-attribute error (`AttributeError`) rather than collapsing both into one generic failure. Getting that distinction right is exactly the kind of convention a new contributor would otherwise miss without guidance, so the demo still proves convention engagement without needing GPU access to do it.

Planned scope:

- Implementation: `vllm/utils/import_utils.py`
- Tests: `tests/utils/test_import_utils.py`. If that path already exists at the pinned revision, extend it; otherwise create it only after confirming `tests/utils/` is the nearest applicable test location and recording representative neighboring tests in the fixture manifest.
- Allowed context: applicable repository instructions, contribution guidance, the implementation file, the selected test file, test configuration, pre-commit configuration, and CI definitions needed to classify the change.
- CI-only checks: any full vLLM suite, platform matrix, or check that cannot run in the fixture environment.

Before implementation, create `demo/SOURCE.md`, `demo/issue.md`, and `demo/fixture-manifest.json`. The manifest records every copied file's upstream path, SHA-256, license status, and role in the demo. Fixture source files must be unmodified copies from the pinned commit; expected patches and outputs live separately under `demo/expected/`.

The fixture is the dependable live-demo path. A full vLLM checkout may be used during development or as an optional integration target, but the live walkthrough must not depend on cloning, downloading models, compiling vLLM, or accessing accelerator hardware.

Run the workflow once against a full checkout at the pinned commit before the screen and record the observed commands and limitations. The fixture demonstrates the same engine and policy against an offline subset; it must never be described as full-repository validation.

## Proposed Artifact

Create a small Python CLI and a shared repository-local engine. Both terminal and IDE workflows invoke the same engine, configuration, state, and validation rules.

Detailed critical user journeys, Python module boundaries, schemas, configuration, and an implementation sequence are defined in [CUJS.md](CUJS.md).

Example CLI:

```text
contrib-pilot init
contrib-pilot run issue.md
contrib-pilot plan issue.md
contrib-pilot scaffold --dry-run
contrib-pilot scaffold --apply
contrib-pilot validate --tier fast
contrib-pilot validate --tier ci
contrib-pilot review
contrib-pilot report
contrib-pilot hooks install
contrib-pilot hooks status
```

`run` is a resumable end-to-end orchestrator over the same stage commands. It pauses for required review and approval, records the last completed stage, and can continue with `contrib-pilot run --resume`. It does not commit, push, or open a PR unless those actions are separately and explicitly requested.

Workflow:

```text
Issue and acceptance criteria
        |
        v
Bounded convention discovery
        |
        v
Implementation and test plan
        |
        v
Proposed patch shown for review
        |
        v
Explicit human approval and apply
        |
        v
Local validation and CI handoff
        |
        v
Multi-role review-ready report
```

The artifact will produce:

- A structured implementation and test plan before material file changes.
- A proposed unified diff for implementation and test scaffolding.
- Plan-time convention constraints (typing, lint policy, allowed libraries) that bind scaffold, distinct from behavioral acceptance criteria.
- Convention, deprecated-API, anti-pattern, boundary, and test-quality findings.
- Commands and results aligned with vLLM's existing lint, test, and CI configuration.
- A record of consulted sources, assumptions, approvals, validation results, risks, and limitations.
- A shared report for Engineering, PM, QA, and DevOps.

## Alternatives Considered

The handout allows several credible approaches: a custom rules file the assistant follows, a guided workflow for a scoped task, exposing docs as searchable context, a scaffolding agent, or a tailored working mode. The chosen design combines a guided workflow with a bounded scaffolding agent and a deterministic engine. Alternatives considered and set aside:

- **Rules/conventions file alone.** No deterministic enforcement, no boundary control, and nothing shared between the CLI and IDE surfaces — conventions would be advisory only, with no evidence trail.
- **Open-ended RAG over the full docs and codebase.** Conflicts directly with the "don't pull context from outside approved boundaries" requirement, and an unbounded retrieval step is not reproducible for a live, offline demo.
- **A custom IDE extension.** Couples the artifact to one editor's API, working against the "team must be able to own and extend this without me" requirement.
- **An autonomous multi-file or multi-issue agent.** Overreaches the SDLC-safety requirement (unattended commits, PRs, or deploys) and duplicates scope reserved for the final-round campaign-mode extension.

The kept design borrows the safe parts of each: bounded, allowlisted context rather than open-ended RAG; a guided command sequence rather than free-form rules; and a scaffolding agent whose output is deterministically re-validated rather than trusted outright.

## CLI and IDE Experience

The CLI is the reference interface, but use of a terminal must not be required for the daily review loop.

### CLI mode

- Emit human-readable output by default and stable JSON with `--format json`.
- Use meaningful exit codes for success, advisory findings, validation failure, boundary violation, and missing context.
- Support `--dry-run` for every command capable of changing files.
- Never modify implementation files until the proposed patch has been displayed and explicitly approved.
- Store run state and reports in a repository-local, ignored working directory.

### IDE mode

Provide editor-agnostic repository files rather than building a custom IDE extension:

- Add documented IDE tasks that invoke `plan`, `validate`, `review`, and `report` through the CLI.
- Emit diagnostics in a stable machine-readable format and, where practical, a compiler-style `path:line:column: severity: message` format that IDE problem matchers can consume.
- Write the proposed patch to a reviewable `.diff` artifact so the IDE's native diff viewer can display it.
- Write the role report as Markdown so it can be previewed inside the IDE.
- Keep all policy and validation behavior in the shared engine; IDE tasks are thin adapters.
- Treat IDE task definitions for a specific editor as optional examples. Do not make the core artifact dependent on Cursor, VS Code, or a proprietary extension API.

The README will demonstrate both a terminal flow and an IDE flow: open the issue, run the plan task, inspect the proposed diff, approve/apply it, view diagnostics, and open the generated report.

## Change Proposal and Human Review Contract

Scaffolding is a proposal workflow, not silent code generation.

1. `plan` produces a structured plan containing acceptance criteria, consulted sources, proposed files, test mapping, assumptions, CI-only requirements, and engine-stamped convention constraints (applicable rule IDs, observed imports, lint policy summary).
2. `scaffold --dry-run` produces a unified diff without changing tracked files. The proposal must follow the plan's convention constraints; the engine rechecks imports and path scope before the diff is written.
3. The user reviews the diff in the terminal or IDE and may edit the plan or reject the proposal.
4. `scaffold --apply` verifies that the repository still matches the recorded base state, asks for explicit approval, applies the patch, and records the approval.
5. `review` compares the current working-tree diff with the approved plan and flags scope drift, unrelated edits, missing tests, and unresolved findings.

The tool must never overwrite user changes. It will stop if the base file hash has changed, a patch no longer applies cleanly, or a proposed path is outside the allowlist.

## Generation Boundary and Failure Behavior

Separate deterministic enforcement from assistant-generated suggestions.

Deterministic responsibilities:

- Configuration and schema validation.
- Path and source boundary enforcement.
- Source inventory and provenance recording.
- File hashing, patch preview/application, and scope-drift detection.
- Command execution, exit-code capture, and report assembly.
- Hard checks such as prohibited paths, missing required evidence, and failed tests.
- Convention stamping: `applicable_rules`, `observed_imports`, and `lint_checks` on `ChangePlan`; AST import inventory; scaffold refusal of new third-party imports when configured.

Assistant-supported responsibilities:

- Interpreting the issue and proposing an implementation plan.
- Selecting representative nearby patterns from approved context.
- Suggesting implementation and test changes that follow engine-stamped convention constraints.
- Explaining advisory quality findings and tradeoffs.

Use structured schemas for plan, findings, validation results, and reports. All provider responses are untrusted input: validate their schema, paths, commands, source references, and size before use.

### Provider contract

```python
class GenerationProvider(Protocol):
    def create_plan(self, request: PlanRequest) -> ChangePlan: ...
    def create_proposal(self, request: ProposalRequest) -> ProposedChange: ...
```

Implement two explicit providers:

- `FixtureProvider` returns versioned, deterministic expected outputs for offline demos and automated tests. It demonstrates orchestration and controls, not live code-generation quality.
- `AssistantProvider` receives only the approved source contents assembled by the Python engine and requests schema-constrained plan and proposal output. It has no repository tools or independent filesystem access within a governed run.

`AssistantProvider` configuration declares the provider/model identifier, timeout, maximum input/output size, and credential environment-variable name. Credentials are never copied into prompts or artifacts. The provider gets a bounded `PlanRequest` or `ProposalRequest`, not a repository path. Malformed output may receive one schema-repair attempt containing only validation errors; it is never silently accepted.

Select the provider explicitly with `--provider fixture|assistant`; do not perform hidden web retrieval or fall back from one provider to another. If assistant/model access is unavailable, deterministic discovery and validation remain usable, and the user may supply a schema-valid plan or complete-file proposal. Reports identify which provider produced each artifact.

## Approved Context and Guardrails

Allowed context:

- The pinned vLLM checkout or bundled deterministic fixture.
- Selected public vLLM documentation captured or explicitly approved for the run.
- Explicitly configured project, test, and CI files.
- The supplied issue and user-approved plan or patch.

Disallowed context:

- Arbitrary web retrieval during the contribution workflow.
- Neighboring or unrelated repositories.
- Secrets, credentials, environment files, and unapproved generated context.
- Paths outside the repository and configured working directory.

The tool records every consulted source. It fails clearly when required information is unavailable or access falls outside the approved boundary. The nearest applicable repository instructions and domain-specific contribution guidance must be discovered before a plan is proposed.

The Python engine is the only component permitted to read governed context. It resolves and validates a path before opening it, rejects symlinks that resolve outside the repository, bounds individual and total context size, and supplies approved content to the provider. Provider-returned paths never authorize new reads.

## Typing, Lint, and Package Conventions at Plan and Scaffold Time

Behavioral acceptance criteria stay numbered in `issue.md` and mapped to tests. Typing style, linter policy, and library choice are **conventions**. They must not be extra acceptance criteria (there is no fair failing test for "use good typing"). They are injected at `plan`, bound at `scaffold`, and enforced later by `validate`.

This is an extension of Phase 2, not a third validation tier and not a new CLI command.

### Why plan and scaffold, not only validate

`validate` is the right place to **run** Ruff/pre-commit on applied files. If conventions appear only then, the assistant can emit `Optional[int]`, a new third-party import, or an unused name, and the contributor pays an extra edit cycle.

`plan` is the right place to **name** which reviewed rules apply and which libraries already exist in approved sources. `scaffold` is the right place to **generate** against those constraints so the first diff is already convention-shaped. `validate` remains the only stage that executes linters.

Do not run Ruff, mypy, or pip inside `plan` or `scaffold`. Those stages must not mutate files, must not introduce commands from issue or provider text, and must stay offline.

### Three products, two owners

| Product | Meaning | Owner | Plan | Scaffold | Validate |
| --- | --- | --- | --- | --- | --- |
| Lint policy | Project Ruff/pre-commit IDs already selected by the repo (`E`, `F`, `UP`, `I`, …) | `CHECK_REGISTRY` + `[[checks]]` with `project-pre-commit-changed-files` | Record the check ids that `validate` will run; parse `[tool.ruff.lint].select` from an allowlisted `pyproject.toml` into a short policy summary | Include that summary in the proposal request so generated text prefers PEP 604 unions, builtin generics, and isort-compatible imports | Execute pre-commit/Ruff on changed files |
| Typing rules | Small, reviewed heuristics Ruff may miss (`Any` on a new public API; `Optional[X]` when neighbors use `X \| None`) | `RULE_REGISTRY` in engine code; `config.toml` only names rule IDs | Stamp `applicable_rules` from config, never from the provider | Pass the same IDs into `ProposalRequest`; assistant follows them | Emit `advisory` `Finding` records with path, line, evidence, remediation |
| Package recommendation | Reuse libraries already imported in approved implementation sources; do not add a dependency | Deterministic import inventory from allowlisted files | Record `observed_imports` (stdlib / first-party / third-party already present) | Reject or flag a proposed import that is not in that set and not stdlib/first-party | Same heuristic on the applied tree; never search PyPI or the web |

Package "recommendation" is closed-world: recommend symbols already in `scheduler.py` / `speculative.py` (or whichever files are approved). Arbitrary web retrieval and "suggest a new PyPI package" remain disallowed context.

### Schema and configuration

Extend `ChangePlan` (schema_version bump is allowed) with engine-owned fields the provider must not author:

- `applicable_rules`: rule IDs copied from config after provider return, the same way `issue_path` and `sources` are stamped today.
- `observed_imports`: sorted import names extracted from approved implementation sources.
- `lint_checks`: check IDs from `config.checks` whose `definition` is a lint/pre-commit registry key.

`PlanRequest` and `ProposalRequest` carry the same three fields so both providers see them. `FixtureProvider` ignores them except as frozen expected JSON. `AssistantProvider` receives them as extra prompt context, still with no tools and no extra file reads.

`config.toml` selects rules; it does not define regexes or command arrays:

```toml
[context]
allowed_sources = [
  "vllm/v1/core/sched/scheduler.py",
  "vllm/config/speculative.py",
  "AGENTS.md",
  "pyproject.toml",
  ".pre-commit-config.yaml",
]

[conventions]
rules = [
  "typing.pep604-union",
  "typing.builtin-generics",
  "typing.any-on-new-api",
  "libs.no-new-third-party",
  "hints.google-docstring",
]

[[checks]]
id = "pre-commit"
tier = "fast"
definition = "project-pre-commit-changed-files"
append_changed_files = true
timeout_seconds = 90
```

`RULE_REGISTRY` lives next to `CHECK_REGISTRY`. Introducing a new rule ID is a code review, not an issue.md edit. Default severity is `advisory`. `libs.no-new-third-party` may be `blocking` at scaffold revalidation when the import is clearly third-party and absent from `observed_imports`; ambiguous cases stay advisory.

### Planner behavior (`planner.py`)

1. Discover convention sources with explicit purposes (`typing-and-lint convention`, `ruff policy`, `agent instructions`) when those paths are in `allowed_sources`. Missing optional convention files are skipped; missing required implementation sources still fail loudly.
2. Parse numbered acceptance criteria as today. A `## Conventions` section in `issue.md` is free text only — no numbered list, so it cannot become an AC.
3. Extract `observed_imports` with the stdlib `ast` module from approved implementation sources. Do not execute those files.
4. Call the provider with issue text, AC hint, sources, `applicable_rules`, `observed_imports`, and `lint_checks`.
5. On return, **overwrite** `applicable_rules`, `observed_imports`, and `lint_checks` from the engine. The provider may put convention notes in `assumptions` (explainability); it cannot add a rule ID or an import to the allowlist.

### Scaffold behavior (`generator.py`)

1. Forward the stamped convention fields on `ProposalRequest`.
2. After schema validation, scan proposed file contents with `ast`. If `libs.no-new-third-party` is active and a non-stdlib, non-first-party import is absent from `observed_imports`, fail the proposal with a boundary error and remediation ("reuse an import already in approved sources, or record a justified new dependency in the plan assumptions and re-plan").
3. Do not fail the proposal for typing heuristics. Those remain advisory at `validate` so a correct functional patch is not discarded for `Optional` vs `|`.
4. Still forbid paths outside the plan. Convention checks do not authorize extra files.

### Validate and report

`validate --tier fast` runs focused tests and, when configured, `project-pre-commit-changed-files`. That is what actually applies Ruff (`ruff-check --fix` / `ruff-format` in vLLM's `.pre-commit-config.yaml`). If pre-commit rewrites files, approval and validation become stale per the existing hook contract.

The same `RULE_REGISTRY` runs as deterministic findings on changed files. `review` and `report` already surface `advisory` without a nonzero exit. Do not hide those findings when the run is otherwise ready.

### Issue.md shape

Keep ACs behavioral. Put convention intent in an unnumbered section, for example:

```markdown
## Conventions

Follow nearby code and these repo rules:
- Typing: PEP 604 unions (`X | None`), builtin generics (`list[int]`).
- Libraries: reuse types already imported in the touched files; no new dependency.
- Hints: Google-style docstrings on new public functions; line length 88.
```

### Out of scope for this extension

- A `--tier lint` flag or a `contrib-pilot lint` command.
- Running mypy/Ruff inside `plan` or `scaffold`.
- Letting the assistant invent rule IDs, Ruff args, or package names from the web.
- Promoting typing heuristics to blocking by default.
- Auto-fixing imports or types; the human still reviews `proposal.diff`.

## Run Integrity, Ownership, and Staleness

At run creation, record:

- Run ID, schema version, tool version, and provider identity.
- Base commit and repository root.
- Staged diff hash and working-tree diff hash.
- Inventory of untracked paths without reading unapproved contents.
- Hashes of issue, configuration, applicable instructions, consulted sources, and target files.
- Validation rule version and exact command specifications.

These values form the run's input fingerprint. The tool distinguishes pre-existing user changes from the proposal delta and never claims unrelated changes as run output.

Every downstream artifact records its direct input hashes. Changing an implementation/test file, issue, configuration, applicable instruction, consulted source, command specification, tool/rule version, or provider output invalidates all dependent stages. `run --resume` recomputes fingerprints before reusing work and reports exactly which dependency became stale.

Approval binds the run ID, proposal hash, base-state fingerprint, approver invocation identity, timestamp, and tool/schema version. `--yes` may suppress a repeated prompt only when that exact approval artifact already exists; it cannot create approval. Approval artifacts are integrity-checked but are local workflow evidence, not cryptographic identity or authorization.

For MVP patching, proposals contain complete UTF-8 text contents for a small allowlisted set of regular files. New text files are supported. Deletes, renames, binary files, symlinks, submodules, and file-mode changes are rejected. Before writing, validate the whole proposal and snapshot affected files in the run directory. Apply through same-filesystem temporary files and attempt rollback on partial failure; report rollback success explicitly rather than claiming transactional atomicity.

## Git Hooks: Early Feedback Without Surprise Mutations

Git hooks are an optional IDE-friendly safety net, not the primary interface and not a place for generation or automatic file modification.

Do not edit `.git/hooks` directly as part of the checked-in artifact because it is unversioned and local to one clone. Instead:

- Store versioned hook entrypoints in a repository directory such as `.contrib-pilot/hooks/`.
- Install them explicitly with `contrib-pilot hooks install`, preferably by configuring a dedicated `core.hooksPath` after showing the exact Git configuration change.
- Detect an existing custom hooks path and refuse to replace it silently. Provide composition instructions or an opt-in wrapper.
- Provide `hooks status` and `hooks uninstall` commands.
- Keep hooks fast, deterministic, offline, and non-mutating.

Proposed hook behavior:

- `pre-commit`: validate staged paths against the allowlist, detect configured prohibited-file patterns, check plan/test mapping, and run only Contribution Copilot's read-only staged-content checks. Print actionable diagnostics and the command for fuller review.
- `commit-msg`: optionally check the configured contribution category or commit convention when relevant.
- `pre-push`: optionally run the fast validation tier and confirm that CI-only checks and unresolved advisories are visible in the report.

Hooks block only objective policy violations or failed required checks. Heuristic findings such as weak assertions or possible anti-patterns are advisory by default and appear in the review report. Developers can bypass hooks using normal Git mechanisms, so CI remains authoritative. Every bypass or hook limitation should be explained honestly rather than presented as a security boundary.

Repository formatting hooks may modify files, so they are not invoked from Contribution Copilot's non-mutating Git hook. An explicit `validate` command may run the repository's existing pre-commit configuration; if it changes any file, the proposal approval and prior validation/report artifacts become stale and the user must review the new diff.

## Safe Command Execution

Checked-in validation configuration is trusted project policy, but commands are still constrained. The MVP does not execute arbitrary command strings from issues, provider output, user-authored plans, or run artifacts.

- Configuration refers to a versioned allowlist of check IDs. Each check maps to a checked-in executable and argument array; no shell command text is accepted.
- Invoke with `shell=False`, an explicit repository working directory, and no substitutions, redirections, or shell metacharacter interpretation.
- Permit only configured executables such as the active Python interpreter, `uv`, and `git`; introducing a new executable requires a configuration change and human review.
- Build the child environment from an allowlist (`PATH`, temporary-directory variables, locale, and explicitly required tool variables). Remove credential, token, proxy, and provider-secret variables unless a check explicitly and visibly requires one.
- Default validation to no network dependency. A network-enabled check is labeled, disabled in the offline demo, and requires explicit opt-in.
- Enforce per-command timeout, total validation timeout, output-byte limit, and process-group termination. Preserve bounded full output as an artifact and show a concise summary.
- Reject paths outside the repository, resolve symlinks before use, and append changed-file arguments only after boundary validation.
- Record the check ID, executable path, arguments, working directory, environment-variable names passed, start/end time, exit status, timeout state, and output hash.

CI uses the same executor and allowlisted check definitions.

## Implementation Plan

### Phase 1: Walking Skeleton and Demo Fixture

- Materialize the pinned vLLM task, source record, and fixture manifest defined above.
- Inventory applicable instructions, contribution guidance, nearby code/tests, pre-commit configuration, test configuration, CI definitions, and security guidance.
- Create the deterministic fixture and record why it is representative.
- Define schemas for configuration, plan, findings, validation results, and multi-role report.
- Implement `init`, `plan`, `scaffold --dry-run`, `scaffold --apply`, `validate`, `review`, `report`, and resumable `run` as a complete thin vertical slice.
- Require patch preview and explicit approval before writes.
- Implement `demo reset` as an idempotent restoration from immutable fixture source plus expected starting-state hashes. It refuses to overwrite unknown user files and resets only the named demo workspace.

### Phase 2: Convention Discovery and Validation

- Discover relevant guidance and nearby patterns using targeted, allowlisted searches.
- Treat `AGENTS.md`, `pyproject.toml`, and `.pre-commit-config.yaml` as optional convention sources when listed in `allowed_sources`.
- Generate a file and test plan before proposing changes.
- Stamp `applicable_rules`, `observed_imports`, and `lint_checks` on `ChangePlan` from config and AST inventory; never trust the provider to author those fields.
- Pass those constraints into `scaffold` so the first diff prefers existing libraries, PEP 604 typing, and the repo's Ruff select set.
- Reuse vLLM's existing commands and configuration rather than creating parallel standards.
- Run the narrowest relevant pytest selection and pre-commit checks supported locally.
- Provide a fast local tier and a fuller CI-oriented tier.
- Identify accelerator, model-evaluation, distributed, or unavailable checks as CI-required without claiming local success.
- Detect selected deprecated APIs and project anti-patterns, including the reviewed typing/library heuristics in `RULE_REGISTRY`.
- Flag behavior changes without corresponding tests.
- Assess assertion quality, positive/negative cases, minimal setup, and acceptance-criteria traceability as explainable heuristics, not proof of test quality.
- Classify findings as blocking, advisory, or CI-required and include the evidence and remediation for each.

### Phase 3: IDE, Hooks, Reporting, and Verification

- Add editor-agnostic diagnostic output and optional example IDE tasks.
- Implement explicit Git-hook install, status, and uninstall flows.
- Generate the proposed diff and Markdown report as IDE-reviewable artifacts.
- Produce role-specific report sections:
  - Engineering: design, changed files, commands, assumptions, disclosure/sign-off readiness, and technical risks.
  - PM: acceptance-criteria coverage, user impact, scope decisions, and deferred work.
  - QA: test cases, edge cases, regression risks, hardware coverage, and manual checks.
  - DevOps: local versus CI-only validation, CI handoff, configuration changes, rollout signals, and rollback considerations.
- Add unit tests for schemas, configuration, boundary enforcement, patch safety, diagnostics, hook installation behavior, and report generation.
- Add an integration test covering issue to plan, dry-run diff, approval/apply, validation, review, and report.
- Test missing model access, missing context, dirty or changed base files, prohibited paths, failed validation, advisory findings, and hook conflicts.
- Rehearse both CLI and IDE flows from the bundled clean fixture.

## CI and Deployment Fit

- CI invokes the same validation engine and allowlisted checks used locally and remains authoritative:

  ```bash
  uv run contrib-pilot validate \
    --tier ci \
    --base-ref "$CI_BASE_REF" \
    --non-interactive \
    --format json
  ```

- CI computes changed files from the configured base and head refs; it does not depend on ignored local run state or local approval artifacts.
- In CI, review readiness means validation evidence only. Human approval and local patch provenance are reported as `not_applicable` unless supplied by an explicitly trusted artifact channel.
- The job uploads `validation.json`, bounded command logs, and `report.md`. CI evidence supersedes local results for the same commit and command fingerprint; it does not rewrite local artifacts.
- Blocking findings or failed required checks return exit code `6`; invalid configuration returns `2`; advisory-only or CI-required results return `0` while remaining visible in artifacts.
- The artifact should integrate through existing project commands where possible; do not create a parallel CI standard merely for the demo.
- Reports distinguish observed local results, planned checks, skipped checks, and CI-only checks.
- Deployment is a gated handoff. The artifact provides readiness evidence, rollout considerations, rollback notes, and unresolved risk; it never deploys automatically.

## Installation, E2E, and Reset Contract

Support Linux with Python 3.12, Git 2.39 or newer, and `uv`. Package the CLI through a `pyproject.toml` entry point and commit `uv.lock`.

Fresh offline-demo flow:

```bash
uv sync --frozen
uv run contrib-pilot doctor
uv run contrib-pilot demo reset
uv run contrib-pilot run demo/issue.md --provider fixture
```

`doctor` checks Python/Git versions, repository identity, configuration, ignored run directory, fixture hashes, provider availability, and required local executables without changing repository files. The documented offline claim assumes Python, Git, uv, and the locked dependency cache are already present; first-time dependency download is not described as offline.

Interactive assistant flow:

```bash
uv run contrib-pilot demo reset
uv run contrib-pilot run demo/issue.md --provider assistant
```

The README records expected runtime for rehearsed fixture and assistant runs, the exact reset scope, supported platform, dependency-cache assumption, and full-checkout rehearsal command. `demo reset` operates only on `demo/workspace/`, verifies the target marker and resolved path, previews affected files, and never runs a broad Git reset or deletion.

## Acceptance Checks

The artifact is complete when:

- A fresh user can run the documented demo from the bundled clean fixture.
- The pinned vLLM revision and representative customer task are recorded without presenting the task as an accepted upstream issue.
- Fixture files match the pinned upstream hashes and are clearly distinguished from full-repository validation.
- `uv sync --frozen`, `doctor`, `demo reset`, and the fixture-provider run form an exact reproducible bootstrap contract.
- A plan is generated before implementation files change.
- A unified diff is presented for review before explicit approval and application.
- Concurrent user edits or changed base hashes prevent unsafe patch application.
- The scaffold follows representative project conventions.
- The plan records engine-stamped convention constraints (rule IDs, observed imports, lint check IDs) and the provider cannot add a rule or a new third-party import to that allowlist.
- Scaffold refuses a proposed third-party import that is absent from `observed_imports` when `libs.no-new-third-party` is configured; typing hints remain advisory until `validate`.
- A relevant test is proposed, or an explicit justification is required.
- Focused pytest, pre-commit, and configured quality checks can be invoked through one command where supported.
- A deliberately deprecated API or selected anti-pattern produces an evidence-backed finding.
- Hard failures and advisory test-quality heuristics are clearly distinguished.
- Package recommendations are closed-world (imports already present in approved sources); no PyPI or web lookup.
- Prohibited context or paths are rejected and reported clearly.
- Terminal and IDE-oriented workflows use the same engine and results.
- `run` reaches the report on the happy path, resumes after interruption, and refuses non-interactive continuation without an exact bound approval.
- Changing a relevant file, rule, configuration, consulted source, command, or tool version invalidates dependent validation, review, report, and commit evidence.
- Pre-existing staged, unstaged, and untracked changes are inventoried and not attributed to the run.
- Fixture and assistant providers are explicitly selected, recorded, schema-validated, and never used as hidden fallbacks.
- Validation executes only reviewed check IDs through the constrained command executor; provider or issue text cannot introduce commands.
- Optional Git hooks install without silently replacing existing hooks and perform no code generation or file mutation.
- Contribution Copilot hooks remain read-only even when the repository's separate formatting hooks are mutating.
- Hardware-dependent checks are labeled CI-required and never reported as locally passing.
- Engineering, PM, QA, and DevOps receive useful sections in the same report.
- Known limitations and unsupported cases are documented.
- The live demo resets and repeats without network access, GPU access, or screenshots.

## Live Walkthrough Plan

Target 20–25 minutes of prepared material, leaving the remainder of the 45-minute session for discussion.

1. **Problem and priority — 3 minutes:** explain the onboarding bottleneck, business impact, scope, and what was deliberately deferred.
2. **Architecture and boundaries — 3 minutes:** show the shared engine, CLI/IDE adapters, approved context, deterministic controls, and assistant boundary.
3. **Happy-path live demo — 10 minutes:** plan the sample issue, inspect sources, review the proposed diff in an IDE or terminal, approve/apply it, validate, and open the multi-role report.
4. **Controlled failure — 4 minutes:** demonstrate a prohibited-path or changed-base rejection and show actionable remediation. Optionally show a fast hook finding.
5. **Tradeoffs and extension — 3–5 minutes:** discuss heuristic limitations, local versus CI evidence, failures encountered, and how account policy or future campaign orchestration can extend the schemas and engine.

No deep architecture deck is required. One compact workflow diagram is sufficient.

## Requirements Traceability

| Technical-screen requirement | Planned evidence | Verification |
| --- | --- | --- |
| Scaffold a correct first contribution | Targeted discovery, structured plan, reviewable patch, and test proposal | Run the sample contribution and compare it with captured nearby patterns |
| Avoid reading the whole codebase | Allowlisted targeted discovery and consulted-source record | Inspect provenance and confirm bounded discovery |
| Catch mistakes early | Required checks plus evidence-backed deprecated API and anti-pattern findings | Inject representative failures before review |
| Follow typing, lint, and library conventions without extra ACs | Engine-stamped plan constraints, scaffold import recheck, Ruff via `validate` pre-commit | Plan lists `observed_imports`/`applicable_rules`; a new third-party import fails scaffold; Ruff `UP`/`I`/`F` run only at validate |
| Strengthen tests | Acceptance mapping and explainable assertion/edge-case heuristics | Show missing-test and advisory weak-test findings |
| Fit existing CI | Shared validation engine, fast/CI tiers, and explicit CI-only checks | Run local checks and inspect the CI handoff |
| Enforce guardrails | Context and path allowlists with observable failures | Attempt a prohibited path |
| Move safely toward deployment | Readiness, rollout, rollback, and gated handoff evidence | Confirm no automatic deployment occurs |
| Stay maintainable | Configuration, schemas, tests, and thin CLI/IDE/hook adapters | Change a convention without changing orchestration code |
| Serve multiple audiences | One shared Markdown report with role-specific views | Review each section against the sample issue |
| Produce a runnable artifact | Offline, resettable fixture and live CLI/IDE flow | Run it live without screenshots or network access |
| Demonstrate judgment | Explicit priority, narrow scope, alternatives, and deferred work | Explain choices during the walkthrough |
| Show honest limitations | Blocking/advisory/CI-required distinctions and unsupported cases | Demonstrate one limitation and how evidence would be obtained |
| Support the final challenge | Separate project conventions, customer policy, and report configuration | Explain account-specific extensions without implementing campaign mode |

## Risks and Controls

- **Scope expansion:** control by completing one issue end to end and deferring campaign orchestration.
- **vLLM installation or hardware failure:** control with a pinned, representative offline fixture and explicit CI-only evidence.
- **Unsafe generated edits:** control with dry-run diffs, base hashes, explicit approval, and refusal to overwrite user changes.
- **Overclaiming heuristic quality checks:** label them advisory and show their evidence.
- **Open-ended library suggestion:** recommend only imports already present in allowlisted sources; never query PyPI or the web.
- **IDE-specific coupling:** keep the engine editor-agnostic and ship only thin task examples.
- **Git-hook surprise or latency:** require explicit installation, preserve existing hook setups, keep checks fast/non-mutating, and rely on CI as authoritative.
- **Hidden model dependency:** document generation boundaries and provide deterministic validation plus user-authored plan/patch inputs when model access is unavailable.

## Future Extension for the Final Challenge

Preserve extension points without implementing them during this screen:

- Separate project conventions from account-specific security, governance, and value metrics.
- Keep schemas stable enough to support multiple issues and role-specific policies later.
- Describe how isolated branches/worktrees, bounded parallelism, quarantine, human approval, and publication throttling could form a governed campaign mode.
- Do not claim multi-issue automation until isolation, conflict detection, CI capacity, and maintainer controls are implemented and tested.

The plan is ready for implementation. The first implementation action is to materialize and hash the pinned demo fixture and verify whether the planned test module is extended or created before writing any generated expected output.
