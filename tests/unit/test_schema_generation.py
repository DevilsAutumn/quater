from __future__ import annotations

from dataclasses import field, make_dataclass
from inspect import Signature
from typing import Annotated, Any

import msgspec

from quater import UploadFile
from quater.params import BoundParameter
from quater.schema import (
    allows_none,
    annotation_schema,
    parameter_required,
    parameter_schema,
    strip_annotated,
    strip_optional,
)

CatalogItem = make_dataclass(
    "CatalogItem",
    [
        ("sku", str),
        ("stock", int),
        ("tags", list[str]),
        ("discontinued", bool, field(default=False)),
    ],
)


class Metrics(msgspec.Struct):
    p95_ms: float
    labels: dict[str, str]
    healthy: bool = True


def bound_parameter(
    *,
    annotation: object,
    default: object = Signature.empty,
    description: str | None = None,
) -> BoundParameter:
    return BoundParameter(
        name="value",
        source="query",
        request_name="value",
        input_name="value",
        annotation=annotation,
        default=default,
        description=description,
    )


def test_annotation_schema_handles_builtin_and_container_types() -> None:
    assert annotation_schema(str) == {"type": "string"}
    assert annotation_schema(bytes) == {"type": "string", "format": "binary"}
    assert annotation_schema(UploadFile) == {"type": "string", "format": "binary"}
    assert annotation_schema(int) == {"type": "integer"}
    assert annotation_schema(float) == {"type": "number"}
    assert annotation_schema(bool) == {"type": "boolean"}
    assert annotation_schema(list) == {"type": "array"}
    assert annotation_schema(dict) == {"type": "object"}
    assert annotation_schema(Any) == {"type": "object"}
    assert annotation_schema(list[int]) == {
        "type": "array",
        "items": {"type": "integer"},
    }
    assert annotation_schema(dict[str, int]) == {"type": "object"}


def test_annotation_schema_describes_msgspec_structs_and_dataclasses() -> None:
    assert annotation_schema(Metrics) == {
        "type": "object",
        "properties": {
            "p95_ms": {"type": "number"},
            "labels": {"type": "object"},
            "healthy": {"type": "boolean"},
        },
        "additionalProperties": False,
        "required": ["p95_ms", "labels"],
    }
    assert annotation_schema(CatalogItem) == {
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "stock": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "discontinued": {"type": "boolean"},
        },
        "additionalProperties": False,
        "required": ["sku", "stock", "tags"],
    }


def test_optional_and_annotated_helpers_strip_metadata_without_losing_nullability() -> (
    None
):
    annotation = Annotated[int | None, "from docs"]

    assert strip_annotated(annotation) == int | None
    assert strip_optional(annotation) is int
    assert allows_none(annotation) is True
    assert parameter_required(bound_parameter(annotation=annotation)) is False


def test_parameter_schema_keeps_only_json_safe_defaults() -> None:
    safe = bound_parameter(
        annotation=int,
        default=25,
        description="Maximum rows to return.",
    )
    unsafe = bound_parameter(annotation=object, default=object())

    assert parameter_schema(safe) == {
        "type": "integer",
        "description": "Maximum rows to return.",
        "default": 25,
    }
    assert parameter_schema(unsafe) == {"type": "object"}
