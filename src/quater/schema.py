"""JSON schema generation shared by OpenAPI and MCP tools."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from inspect import Signature
from types import UnionType
from typing import Annotated, Any, Union, cast, get_args, get_origin

from quater.params import BoundParameter

_EMPTY = object()


def annotation_schema(annotation: object) -> dict[str, object]:
    annotation = strip_annotated(annotation)
    annotation = strip_optional(annotation)
    if annotation is str:
        return {"type": "string"}
    if annotation is bytes:
        return {"type": "string", "format": "binary"}
    if _is_upload_file(annotation):
        return {"type": "string", "format": "binary"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is list:
        return {"type": "array"}
    if annotation is dict or annotation in {_EMPTY, object, Any}:
        return {"type": "object"}

    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        item_schema = annotation_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}
    if origin is dict:
        return {"type": "object"}
    if _is_msgspec_struct(annotation):
        return _msgspec_struct_schema(annotation)
    if is_dataclass(annotation) and isinstance(annotation, type):
        return _dataclass_schema(annotation)
    return {"type": "object"}


def parameter_required(parameter: BoundParameter) -> bool:
    return parameter.default is Signature.empty and not allows_none(
        parameter.annotation
    )


def parameter_schema(
    parameter: BoundParameter,
    *,
    include_description: bool = True,
) -> dict[str, object]:
    schema = annotation_schema(parameter.annotation)
    if include_description and parameter.description:
        schema["description"] = parameter.description
    if parameter.default is not Signature.empty and _is_json_schema_default(
        parameter.default
    ):
        schema["default"] = parameter.default
    return schema


def strip_annotated(annotation: object) -> object:
    if get_origin(annotation) is not Annotated:
        return annotation
    args = get_args(annotation)
    return args[0] if args else annotation


def strip_optional(annotation: object) -> object:
    annotation = strip_annotated(annotation)
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return annotation
    args = tuple(arg for arg in get_args(annotation) if arg is not type(None))
    return args[0] if len(args) == 1 else annotation


def allows_none(annotation: object) -> bool:
    annotation = strip_annotated(annotation)
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return False
    return type(None) in get_args(annotation)


def _msgspec_struct_schema(annotation: object) -> dict[str, object]:
    import msgspec

    properties: dict[str, object] = {}
    required: list[str] = []
    for field in msgspec.structs.fields(cast(type[Any], annotation)):
        properties[field.name] = annotation_schema(field.type)
        if field.required:
            required.append(field.name)

    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _dataclass_schema(annotation: type[object]) -> dict[str, object]:
    from dataclasses import MISSING

    properties: dict[str, object] = {}
    required: list[str] = []
    for field in fields(cast(Any, annotation)):
        properties[field.name] = annotation_schema(field.type)
        if field.default is MISSING and field.default_factory is MISSING:
            required.append(field.name)

    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _is_msgspec_struct(annotation: object) -> bool:
    import msgspec

    return isinstance(annotation, type) and issubclass(annotation, msgspec.Struct)


def _is_upload_file(annotation: object) -> bool:
    from quater.formdata import UploadFile

    return annotation is UploadFile


def _is_json_schema_default(value: object) -> bool:
    try:
        from quater.serialization import dumps_json

        dumps_json(value)
    except (TypeError, ValueError):
        return False
    return True
