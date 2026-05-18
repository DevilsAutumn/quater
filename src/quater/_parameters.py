"""Public handler parameter marker functions."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import Signature
from typing import Any, Literal, cast

ParameterSource = Literal["path", "query", "body", "header", "cookie", "form", "file"]


@dataclass(slots=True, frozen=True)
class ParameterMarker:
    source: ParameterSource
    default: object
    alias: str | None
    description: str | None
    convert_underscores: bool = True


def Query(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any:
    """Declare a query-string parameter for binding and generated schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="query",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
        ),
    )


def Path(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any:
    """Declare a route path parameter for binding and generated schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="path",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
        ),
    )


def Body(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any:
    """Declare a JSON request body parameter for binding and schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="body",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
        ),
    )


def Form(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any:
    """Declare a form field parameter for binding and generated schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="form",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
        ),
    )


def File(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any:
    """Declare a multipart file parameter for binding and generated schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="file",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
        ),
    )


def Header(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
    convert_underscores: bool = True,
) -> Any:
    """Declare an HTTP header parameter for binding and generated schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="header",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
            convert_underscores=convert_underscores,
        ),
    )


def Cookie(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any:
    """Declare an HTTP cookie parameter for binding and generated schemas."""

    return cast(
        Any,
        ParameterMarker(
            source="cookie",
            default=_marker_default(default),
            alias=_clean_alias(alias),
            description=_clean_description(description),
        ),
    )


def is_parameter_marker(value: object) -> bool:
    return isinstance(value, ParameterMarker)


def _marker_default(value: object) -> object:
    if value is ...:
        return Signature.empty
    return value


def _clean_alias(value: str | None) -> str | None:
    if value is None:
        return None
    if not value:
        raise ValueError("Parameter alias must not be empty")
    if any(_is_control_character(char) for char in value):
        raise ValueError("Parameter alias must not contain control characters")
    return value


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_control_character(value: str) -> bool:
    return ord(value) < 32 or ord(value) == 127


__all__ = [
    "Body",
    "Cookie",
    "File",
    "Form",
    "Header",
    "ParameterMarker",
    "ParameterSource",
    "Path",
    "Query",
    "is_parameter_marker",
]
