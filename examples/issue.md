# Short title of the first contribution

One or two paragraphs: what is wrong or missing today, who hits it, and
what "done" looks like. Name the symbols or files involved. Do not attach
an unbounded refactor.

## Acceptance criteria

1. Observable behavior a test can fail on before the change.
2. A second independent check (edge case, error type, or non-regression).
3. Focused tests run without extra hardware or network.

## Scope

- Implementation: `src/<package>/<module>.py`
- Tests: `tests/test_<module>.py` (extend an existing file when one exists)
- Out of scope: neighboring modules, public API breaks, drive-by cleanup
