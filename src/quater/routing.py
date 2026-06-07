"""Route path parsing and conversion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from quater.exceptions import RouteBindingError

ParamConverter: TypeAlias = Callable[[str], object]


def convert_int_path_value(raw_value: str) -> int:
    """Convert the canonical ``:int`` path form shared by every surface."""
    # Match the native router's `[0-9]+` rule. Plain int() is not validation:
    # it accepts signs, underscores, whitespace, and non-ASCII digits.
    if not raw_value or not raw_value.isascii() or not raw_value.isdigit():
        raise ValueError("invalid int path value")
    return int(raw_value)


@dataclass(slots=True, frozen=True)
class StaticSegment:
    value: str


@dataclass(slots=True, frozen=True)
class ParamSegment:
    name: str
    converter_name: str
    converter: ParamConverter


RouteSegment: TypeAlias = StaticSegment | ParamSegment


@dataclass(slots=True, frozen=True)
class RoutePattern:
    path: str
    segments: tuple[RouteSegment, ...]
    param_names: frozenset[str]

    @property
    def shape(self) -> tuple[tuple[str, str], ...]:
        parts: list[tuple[str, str]] = []
        for segment in self.segments:
            if isinstance(segment, StaticSegment):
                parts.append(("static", segment.value))
            else:
                parts.append(("param", segment.converter_name))
        return tuple(parts)


def parse_route_pattern(path: str) -> RoutePattern:
    if not path.startswith("/"):
        raise RouteBindingError("Route paths must start with '/'")

    names: set[str] = set()
    segments: list[RouteSegment] = []
    for raw_segment in _split_path(path):
        if raw_segment.startswith("{") or raw_segment.endswith("}"):
            segments.append(_parse_param_segment(raw_segment, names))
        else:
            segments.append(StaticSegment(raw_segment))

    return RoutePattern(
        path=path,
        segments=tuple(segments),
        param_names=frozenset(names),
    )


def _split_path(path: str) -> tuple[str, ...]:
    if path == "/":
        return ()
    return tuple(segment for segment in path.strip("/").split("/") if segment)


def _parse_param_segment(raw_segment: str, names: set[str]) -> ParamSegment:
    if not raw_segment.startswith("{") or not raw_segment.endswith("}"):
        raise RouteBindingError(f"Invalid route segment: {raw_segment!r}")

    body = raw_segment[1:-1]
    if not body:
        raise RouteBindingError("Path parameters must have a name")

    if ":" in body:
        name, converter_name = body.split(":", 1)
    else:
        name, converter_name = body, "str"

    if not name.isidentifier():
        raise RouteBindingError(f"Invalid path parameter name: {name!r}")
    if name in names:
        raise RouteBindingError(f"Duplicate path parameter name: {name!r}")
    names.add(name)

    if converter_name == "str":
        converter: ParamConverter = str
    elif converter_name == "int":
        converter = convert_int_path_value
    else:
        raise RouteBindingError(f"Unsupported path converter: {converter_name!r}")

    return ParamSegment(name=name, converter_name=converter_name, converter=converter)
