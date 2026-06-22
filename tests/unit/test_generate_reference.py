"""Unit tests for the signature formatting helpers in the docs generator.

``format_signature``, ``split_top_level_commas``, and ``clean_signature`` in
``scripts/generate_reference.py`` produce the public signatures rendered in the
API reference. Pinning their rules here keeps small formatter regressions
debuggable without having to inspect a generated Markdown diff.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast


def _load_generate_reference() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "generate_reference.py"
    spec = importlib.util.spec_from_file_location("generate_reference", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_module = _load_generate_reference()
format_signature = cast(Callable[..., str], _module.format_signature)
split_top_level_commas = cast(
    Callable[[str], list[str]], _module.split_top_level_commas
)
clean_signature = cast(Callable[[str], str], _module.clean_signature)


class TestFormatSignature:
    def test_short_signature_stays_one_line(self) -> None:
        signature = "def foo(a: int, b: int) -> int"

        assert format_signature(signature) == signature

    def test_signature_at_max_width_stays_one_line(self) -> None:
        signature = (
            "def foo(alpha: int, beta: int, gamma1: int, "
            "delta_param: int, epsilon_value: int) -> int"
        )
        assert len(signature) == 88

        assert format_signature(signature) == signature

    def test_signature_over_max_width_wraps_one_arg_per_line(self) -> None:
        signature = "def foo(alpha: int, beta: int, gamma: int)"

        assert format_signature(signature, max_width=20) == (
            "def foo(\n    alpha: int,\n    beta: int,\n    gamma: int,\n)"
        )

    def test_missing_paren_returns_unchanged(self) -> None:
        signature = "x" * 100

        assert format_signature(signature) == signature

    def test_empty_args_returns_unchanged(self) -> None:
        signature = "def foo() -> " + "X" * 100

        assert format_signature(signature) == signature

    def test_single_long_arg_wraps_with_trailing_comma(self) -> None:
        signature = "def foo(alpha: VeryLongTypeName)"

        assert format_signature(signature, max_width=20) == (
            "def foo(\n    alpha: VeryLongTypeName,\n)"
        )

    def test_tail_preserved_after_wrap(self) -> None:
        signature = "def foo(a: int, b: int) -> ReturnType"

        assert format_signature(signature, max_width=20) == (
            "def foo(\n    a: int,\n    b: int,\n) -> ReturnType"
        )

    def test_nested_generic_argument_not_split_when_wrapping(self) -> None:
        signature = "def foo(a: dict[str, int], b: int)"

        assert format_signature(signature, max_width=20) == (
            "def foo(\n    a: dict[str, int],\n    b: int,\n)"
        )


class TestSplitTopLevelCommas:
    def test_empty_string_returns_empty_list(self) -> None:
        assert split_top_level_commas("") == []

    def test_single_value_returned_as_one_part(self) -> None:
        assert split_top_level_commas("a: int") == ["a: int"]

    def test_nested_generic_not_split(self) -> None:
        assert split_top_level_commas("a: dict[str, int], b: int") == [
            "a: dict[str, int]",
            "b: int",
        ]

    def test_deeply_nested_generic_not_split(self) -> None:
        assert split_top_level_commas(
            "a: dict[str, list[tuple[int, int]]], b: int"
        ) == ["a: dict[str, list[tuple[int, int]]]", "b: int"]

    def test_single_quoted_comma_not_split(self) -> None:
        assert split_top_level_commas("a: Literal['x,y'], b: int") == [
            "a: Literal['x,y']",
            "b: int",
        ]

    def test_double_quoted_comma_not_split(self) -> None:
        assert split_top_level_commas('a: Literal["x,y"], b: int') == [
            'a: Literal["x,y"]',
            "b: int",
        ]

    def test_escaped_quote_inside_string_does_not_end_string(self) -> None:
        value = r"a: str = 'it\'s, ok', b: int"

        assert split_top_level_commas(value) == [
            r"a: str = 'it\'s, ok'",
            "b: int",
        ]

    def test_paren_default_value_not_split(self) -> None:
        assert split_top_level_commas("methods=('GET', 'POST'), other: int") == [
            "methods=('GET', 'POST')",
            "other: int",
        ]

    def test_whitespace_around_parts_is_stripped(self) -> None:
        assert split_top_level_commas("  a: int  ,  b: int  ") == [
            "a: int",
            "b: int",
        ]

    def test_trailing_comma_does_not_produce_empty_part(self) -> None:
        assert split_top_level_commas("a: int,") == ["a: int"]


class TestCleanSignature:
    def test_signature_without_known_sentinels_is_unchanged(self) -> None:
        signature = "def foo(a: int, b: int) -> int"

        assert clean_signature(signature) == signature

    def test_docs_path_unset_sentinel_replaced_with_public_default(self) -> None:
        signature = "Quater(docs_path: str | None | _Unset = _UNSET)"

        assert clean_signature(signature) == ("Quater(docs_path: str | None = '/docs')")

    def test_mcp_protocol_version_sentinel_replaced_with_literal(self) -> None:
        signature = "Quater(version=_MCP_PROTOCOL_VERSION)"

        assert clean_signature(signature) == "Quater(version='2025-11-25')"

    def test_multiple_unset_defaults_all_replaced(self) -> None:
        signature = (
            "Quater("
            "docs_path: str | None | _Unset = _UNSET, "
            "openapi_path: str | None | _Unset = _UNSET"
            ")"
        )

        assert clean_signature(signature) == (
            "Quater("
            "docs_path: str | None = '/docs', "
            "openapi_path: str | None = '/openapi.json'"
            ")"
        )

    def test_empty_str_map_factory_replaced_with_ellipsis(self) -> None:
        signature = "Quater(metadata=_empty_str_map())"

        assert clean_signature(signature) == "Quater(metadata=...)"

    def test_default_methods_sentinel_replaced_with_public_tuple(self) -> None:
        signature = "Route(methods=_DEFAULT_METHODS)"

        assert clean_signature(signature) == (
            "Route(methods="
            "('DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT')"
            ")"
        )
