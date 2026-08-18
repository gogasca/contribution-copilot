# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
from unittest.mock import MagicMock, patch

import pytest

from vllm.utils.import_utils import (
    PlaceholderModule,
    _has_module,
    resolve_obj_by_qualname,
)


def _raises_module_not_found():
    return pytest.raises(ModuleNotFoundError, match="No module named")


def test_placeholder_module_error_handling():
    placeholder = PlaceholderModule("placeholder_1234")

    with _raises_module_not_found():
        int(placeholder)

    with _raises_module_not_found():
        placeholder()

    with _raises_module_not_found():
        _ = placeholder.some_attr

    with _raises_module_not_found():
        # Test conflict with internal __name attribute
        _ = placeholder.name

    # OK to print the placeholder or use it in a f-string
    _ = repr(placeholder)
    _ = str(placeholder)

    # No error yet; only error when it is used downstream
    placeholder_attr = placeholder.placeholder_attr("attr")

    with _raises_module_not_found():
        int(placeholder_attr)

    with _raises_module_not_found():
        placeholder_attr()

    with _raises_module_not_found():
        _ = placeholder_attr.some_attr

    with _raises_module_not_found():
        # Test conflict with internal __module attribute
        _ = placeholder_attr.module


class TestHasModule:
    """Tests for _has_module with trial import verification."""

    def setup_method(self):
        # Clear the @cache between tests so each test gets a fresh call
        _has_module.cache_clear()

    def test_returns_true_for_importable_stdlib_module(self):
        assert _has_module("json") is True

    def test_returns_false_for_nonexistent_module(self):
        assert _has_module("nonexistent_module_xyz_12345") is False

    def test_returns_false_when_find_spec_succeeds_but_import_fails(self):
        """Simulate a native extension whose shared library is missing.

        ``find_spec`` finds the package on disk, but the actual import
        raises ``ImportError`` (e.g. missing ``libcudart.so``).
        """
        fake_spec = MagicMock()

        with (
            patch(
                "vllm.utils.import_utils.importlib.util.find_spec",
                return_value=fake_spec,
            ),
            patch(
                "vllm.utils.import_utils.importlib.import_module",
                side_effect=ImportError(
                    "libcudart.so.12: cannot open shared object file"
                ),
            ),
        ):
            assert _has_module("fake_native_ext") is False

    def test_returns_false_when_find_spec_raises(self):
        """``find_spec`` itself can raise for dotted names whose parent package
        fails to import. This should be treated as the module being unavailable.
        """
        with patch(
            "vllm.utils.import_utils.importlib.util.find_spec",
            side_effect=ModuleNotFoundError("No module named 'fake_parent'"),
        ):
            assert _has_module("fake_parent.child") is False

    def test_result_is_cached(self):
        """Verify the @cache decorator prevents repeated imports."""
        _has_module("json")  # prime the cache

        with patch("vllm.utils.import_utils.importlib.util.find_spec") as mock_spec:
            result = _has_module("json")  # should hit cache
            mock_spec.assert_not_called()
            assert result is True


class TestResolveObjByQualname:
    """Tests for resolve_obj_by_qualname's malformed-input handling."""

    @pytest.mark.parametrize("qualname", ["", "no_dot_here"])
    def test_raises_value_error_for_malformed_qualname(self, qualname):
        with pytest.raises(ValueError, match="fully qualified name"):
            resolve_obj_by_qualname(qualname)

    def test_resolves_valid_stdlib_qualname(self):
        import json

        assert resolve_obj_by_qualname("json.dumps") is json.dumps

    def test_raises_attribute_error_for_missing_object(self):
        with pytest.raises(AttributeError):
            resolve_obj_by_qualname("json.this_attribute_does_not_exist")
