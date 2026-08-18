# Improve error handling in `resolve_obj_by_qualname`

`vllm.utils.import_utils.resolve_obj_by_qualname(qualname)` splits its
argument on the last `.` and imports the left-hand side as a module. When
`qualname` has no `.` (including the empty string), `str.rsplit(".", 1)`
returns a single-element list, so the unpacking assignment
`module_name, obj_name = qualname.rsplit(".", 1)` already raises
`ValueError` — but with the unhelpful default message
`"not enough values to unpack (expected 2, got 1)"`. A caller (or a new
contributor debugging a caller) gets no indication that a fully qualified
`module.attribute` name was expected.

Existing behavior for a missing attribute on a valid module must be left
alone: `getattr(module, obj_name)` should keep raising `AttributeError`,
not be reclassified as malformed input.

## Acceptance criteria

1. Empty strings and names without `.` raise `ValueError` with guidance that a fully qualified `module.attribute` name is required.
2. A valid standard-library qualified name still resolves successfully.
3. A valid module with a missing object continues to raise `AttributeError` rather than being reclassified as malformed input.
4. Focused positive and negative tests run without GPU or model access.

## Scope

- Implementation: `vllm/utils/import_utils.py`
- Tests: `tests/utils_/test_import_utils.py` (extend the existing file — do not create `tests/utils/`, which does not exist upstream)
