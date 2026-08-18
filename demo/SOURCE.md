# Demo Fixture Provenance

- **Repository:** https://github.com/vllm-project/vllm
- **Commit:** [`e0e5a7fb2808504ba86c94f7b379e38496002fd0`](https://github.com/vllm-project/vllm/commit/e0e5a7fb2808504ba86c94f7b379e38496002fd0)
- **Retrieval date:** 2026-08-18
- **License:** Apache-2.0

## What was verified against the real repository before this fixture was built

- `vllm/utils/import_utils.py` exists at the pinned commit and contains
  `resolve_obj_by_qualname` exactly as copied into `demo/fixture/`.
- **`tests/utils/` does not exist upstream.** The nearest applicable test
  location is `tests/utils_/` (trailing underscore, to avoid colliding with
  the unrelated `tests/utils.py` helper module), and
  `tests/utils_/test_import_utils.py` already exists there. plan.MD's
  originally guessed path (`tests/utils/test_import_utils.py`) was wrong;
  this fixture uses the verified real path and **extends** the existing
  file rather than creating a new one.
- `tests/utils_/test_import_utils.py` has **no existing coverage** for
  `resolve_obj_by_qualname` — confirmed by grepping the fetched file. The
  bug this demo fixes is real: `qualname.rsplit(".", 1)` on a string with
  no `.` already raises `ValueError`, but with the unhelpful default
  message `"not enough values to unpack (expected 2, got 1)"`, not
  actionable guidance.

See `fixture-manifest.json` for exact upstream paths, SHA-256 hashes, and
which files are unmodified upstream copies (`role: "source"`) versus local
scaffolding needed to make the fixture importable standalone
(`role: "fixture-scaffold"` — `vllm/logger.py` and the `__init__.py`
package markers are **not** upstream files).

## Why a subset fixture instead of a full checkout

The live walkthrough must not depend on cloning, downloading models,
compiling vLLM, or accessing accelerator hardware (plan.MD "Pinned Demo
Definition"). `demo/fixture/` bundles only the two real source files plus
the minimal scaffolding needed to import and test them in isolation. This
fixture demonstrates the same engine and policy against an offline subset;
it is never claimed to be full-repository validation.

`contrib-pilot demo reset` copies `demo/fixture/` → `demo/workspace/`,
which is the mutable directory the CLI actually operates on during the
demo.
