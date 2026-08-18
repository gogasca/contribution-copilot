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

## Quickstart (once implemented)

```bash
uv sync --frozen
uv run contrib-pilot doctor
uv run contrib-pilot demo reset
uv run contrib-pilot run demo/issue.md --provider fixture
```

See CUJS.md's Developer Quickstart for the full clone-to-PR flow, and plan.MD's Installation, E2E, and Reset Contract for the offline-demo guarantees.
