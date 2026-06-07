"""Unit tests for route path parsing.

``parse_route_pattern`` underpins routing, tool/action registration, and OpenAPI
generation. Its ``shape`` is what conflict detection compares, so the parsing
contract and the shape projection are pinned here directly.
"""

from __future__ import annotations

import pytest

from quater.exceptions import RouteBindingError
from quater.routing import (
    ParamSegment,
    StaticSegment,
    convert_int_path_value,
    parse_route_pattern,
)


def test_root_path_has_no_segments() -> None:
    pattern = parse_route_pattern("/")

    assert pattern.segments == ()
    assert pattern.shape == ()
    assert pattern.param_names == frozenset()


def test_static_and_param_segments_are_parsed() -> None:
    pattern = parse_route_pattern("/users/{id:int}/posts")

    assert pattern.param_names == frozenset({"id"})
    assert pattern.segments == (
        StaticSegment("users"),
        ParamSegment(name="id", converter_name="int", converter=convert_int_path_value),
        StaticSegment("posts"),
    )
    assert pattern.shape == (
        ("static", "users"),
        ("param", "int"),
        ("static", "posts"),
    )


@pytest.mark.parametrize(("raw_value", "expected"), [("0", 0), ("42", 42), ("007", 7)])
def test_int_path_converter_accepts_canonical_ascii_digits(
    raw_value: str,
    expected: int,
) -> None:
    assert convert_int_path_value(raw_value) == expected


@pytest.mark.parametrize("raw_value", ["-5", "+7", "1_000", "١٢٣", " 7", "7\n"])
def test_int_path_converter_rejects_non_canonical_values(raw_value: str) -> None:
    with pytest.raises(ValueError, match="invalid int path value"):
        convert_int_path_value(raw_value)


def test_default_converter_is_str() -> None:
    pattern = parse_route_pattern("/users/{name}")

    segment = pattern.segments[1]
    assert isinstance(segment, ParamSegment)
    assert segment.converter_name == "str"
    assert segment.converter is str


def test_shape_distinguishes_converter_types() -> None:
    # Conflict detection relies on shape: two paths with the same structure but
    # different converters must produce different shapes.
    assert parse_route_pattern("/u/{id:int}").shape != (
        parse_route_pattern("/u/{id}").shape
    )
    # ...while differing only by parameter name yields the same shape.
    assert (
        parse_route_pattern("/u/{id}").shape == parse_route_pattern("/u/{name}").shape
    )


def test_rejects_path_without_leading_slash() -> None:
    with pytest.raises(RouteBindingError, match="must start with '/'"):
        parse_route_pattern("users/{id}")


def test_rejects_empty_parameter_name() -> None:
    with pytest.raises(RouteBindingError, match="must have a name"):
        parse_route_pattern("/users/{}")


def test_rejects_unbalanced_braces() -> None:
    with pytest.raises(RouteBindingError, match="Invalid route segment"):
        parse_route_pattern("/users/{id")


def test_rejects_non_identifier_parameter_name() -> None:
    with pytest.raises(RouteBindingError, match="Invalid path parameter name"):
        parse_route_pattern("/users/{1st}")


def test_rejects_duplicate_parameter_names() -> None:
    with pytest.raises(RouteBindingError, match="Duplicate path parameter name"):
        parse_route_pattern("/users/{id}/things/{id}")


def test_rejects_unsupported_converter() -> None:
    with pytest.raises(RouteBindingError, match="Unsupported path converter"):
        parse_route_pattern("/users/{id:uuid}")
