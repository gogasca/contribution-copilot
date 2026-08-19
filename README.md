# Contribution Copilot

A repository-local CLI and shared engine that carries a new engineer's first contribution through plan → scaffold → validate → review → report, with a human approval gate before any tracked file changes. Built as the technical-screen artifact for a Solutions Architect role, using `vllm-project/vllm` as the stand-in for a customer's convention-heavy internal library.

## Start here

| Doc | Answers | Read for |
|---|---|---|
| [plan.MD](plan.MD) | Why build this, for whom, what's in/out of scope | Business priority, pinned demo definition, requirements traceability, risks, live walkthrough plan |
| [CUJS.md](CUJS.md) | How an engineer actually uses it | Critical user journeys (CUJ 1–9), the Developer Quickstart (clone → PR), the Python module/data-model spec, the demo script |
| [DESIGN.md](DESIGN.md) | What to build, precisely | Concise technical reference — stack, module layout, pydantic models, state machine, generation boundary, safety mechanisms, exit codes |

Suggested order: **plan.MD** for the case and constraints, then **CUJS.md** for how it behaves end to end, then **DESIGN.md** as the standing implementation reference while building.

## One-line architecture

Three thin adapters — CLI, IDE tasks, Git hooks — call into one shared, deterministic engine. Assistant output (plan/proposal) is always re-validated by that deterministic core before anything is written or reported; nothing mutates a tracked file until a human explicitly approves it.

## Quickstart

All `demo reset` / `doctor` commands run from the **repo root**. All `plan` / `run` /
`scaffold` / `validate` / `review` / `report` commands run from **`demo/workspace`**
(that nested git repo has the demo `config.toml`). `issue.md` lives in `demo/`,
one directory above the workspace.

```bash
uv sync                                  # skip if this fails with Access denied on OneDrive
uv run contrib-pilot doctor
uv run contrib-pilot demo reset          # copies demo/fixture/ → demo/workspace/
cd demo/workspace                        # required — not demo/
uv run --project ../.. contrib-pilot run ../issue.md --provider fixture
```

`--project ../..` tells `uv` to use this package while the cwd is the workspace.
`run` is the one-shot orchestrator: plan → scaffold → validate → review → report.
It pauses once for approval before writing tracked files; confirm `y`.

To reopen the report later, still from `demo/workspace`:

```bash
uv run --project ../.. contrib-pilot report
```

To continue an interrupted run: `... run ../issue.md --resume`.

## Commands

Demo prefix from `demo/workspace`: `uv run --project ../.. contrib-pilot …`  
Setup prefix from the repo root: `uv run contrib-pilot …`

### Setup (repo root)

| Command | What it does | Flags |
|---|---|---|
| `doctor` | Checks Python, Git, fixture config, and the demo manifest. Does not change files. | none |
| `demo reset` | Recreates `demo/workspace/` from `demo/fixture/`. | none |
| `init` | Validates `config.toml` and creates the ignored run directory. Used on a real clone, not required for the bundled demo. | `--path` repo (default: cwd) |

### Contribution flow (`demo/workspace`)

Run these in order, or use `run` to do them in one pass:

`plan` → `scaffold --dry-run` → `scaffold --apply` → `validate` → `review` → `report`

| Command | What it does | Flags / args |
|---|---|---|
| `plan ISSUE` | Writes a bounded plan only (`plan.json` / `plan.md`). No source files change. | `ISSUE` path to `issue.md`; `--provider fixture\|assistant` (default `fixture`); `--format human\|json` |
| `scaffold --dry-run` | Writes `proposal.diff` from the plan. Still no tracked-file writes. | `--dry-run` (required vs `--apply`); `--provider fixture\|assistant` |
| `scaffold --apply` | Applies that proposal after rechecking base hashes. | `--apply`; `--yes` skip the confirm prompt; `--provider` unused on apply (uses saved proposal) |
| `validate` | Runs checks (tests). Does **not** ask whether the diff matches the plan. | `--tier fast\|ci` (default `fast`); `--format human\|json\|compiler`; `--base-ref` commit |
| `review` | Asks whether the current diff still matches the plan. Does **not** re-run tests; uses the last `validate` result. | none |
| `report` | Renders `report.md` / `report.json` from already-recorded plan, proposal, validation, and review. | `--provider fixture\|assistant` |
| `run ISSUE` | One-shot: plan → scaffold → validate → review → report. Pauses once for approval before writing files. | `ISSUE`; `--provider fixture\|assistant`; `--resume`; `--run-id`; `--stop-after STAGE`; `--non-interactive` |

`--tier fast` = local checks only (here: focused pytest). `--tier ci` = those plus CI-only checks (here: GPU integration stays `ci_required` with no GPU).

`--provider fixture` uses the checked-in expected plan/patch (offline demo). `--provider assistant` calls a live model.

### Optional

| Command | What it does | Flags |
|---|---|---|
| `hooks status` | Shows whether Git `core.hooksPath` is managed by this tool. | none |
| `hooks install` | Points Git at the bundled hook scripts. | `--yes` skip confirm |
| `hooks uninstall` | Restores the previous hooks path. | none |
| `commit prepare` | Suggests a commit message and prints `git add` / `git commit` lines. Never stages or commits. | none |
| `hook NAME` | Invoked by installed hook scripts (`pre-commit`, `commit-msg`, `pre-push`), not by a human. | `NAME` |

See CUJS.md's Developer Quickstart for the full clone-to-PR flow, and plan.MD's Installation, E2E, and Reset Contract for the offline-demo guarantees.
