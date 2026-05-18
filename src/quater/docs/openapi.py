"""OpenAPI schema generation from Quater route metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from inspect import Signature
from typing import get_type_hints

from quater.core import RouteDefinition
from quater.params import BoundParameter, HandlerPlan, build_handler_plan
from quater.request import Request
from quater.response import Response
from quater.routing import (
    ParamSegment,
    RoutePattern,
    StaticSegment,
    parse_route_pattern,
)
from quater.schema import (
    annotation_schema,
    parameter_required,
    parameter_schema,
    strip_optional,
)

OPENAPI_VERSION = "3.1.1"


def build_openapi_schema(
    routes: Iterable[RouteDefinition],
    *,
    title: str,
    version: str,
) -> dict[str, object]:
    paths: dict[str, object] = {}
    operation_ids: set[str] = set()

    for route in routes:
        if route.metadata.get("include_in_openapi") is False:
            continue

        pattern = parse_route_pattern(route.path)
        handler_plan = build_handler_plan(
            route.handler,
            path_param_names=pattern.param_names,
            inject=route.inject,
        )
        path = _openapi_path(pattern)
        path_item = paths.setdefault(path, {})
        if not isinstance(path_item, dict):
            continue

        operation_id = _operation_id(route, operation_ids)
        path_item[route.method.lower()] = _operation(
            route,
            handler_plan,
            operation_id=operation_id,
        )

    return {
        "openapi": OPENAPI_VERSION,
        "info": {"title": title, "version": version},
        "paths": paths,
    }


def _operation(
    route: RouteDefinition,
    handler_plan: HandlerPlan,
    *,
    operation_id: str,
) -> dict[str, object]:
    operation: dict[str, object] = {
        "operationId": operation_id,
        "summary": _summary(route),
        "responses": _responses(route),
    }

    if route.description is not None:
        operation["description"] = route.description

    tags = _string_list_metadata(route.metadata.get("tags"))
    if tags:
        operation["tags"] = tags

    parameters = _parameters(handler_plan)
    if parameters:
        operation["parameters"] = parameters

    request_body = _request_body(handler_plan)
    if request_body is not None:
        operation["requestBody"] = request_body

    if route.auth is not None:
        operation["x-quater-auth"] = "required"

    extra = route.metadata.get("openapi_extra")
    if isinstance(extra, Mapping):
        operation.update({str(key): value for key, value in extra.items()})

    return operation


def _parameters(handler_plan: HandlerPlan) -> list[dict[str, object]]:
    parameters: list[dict[str, object]] = []
    for parameter in handler_plan.parameters:
        if parameter.source not in {"path", "query", "header", "cookie"}:
            continue

        required = parameter.source == "path" or parameter_required(parameter)
        item: dict[str, object] = {
            "name": parameter.request_name,
            "in": parameter.source,
            "required": required,
            "schema": parameter_schema(parameter, include_description=False),
        }
        if parameter.description:
            item["description"] = parameter.description
        parameters.append(item)
    return parameters


def _request_body(handler_plan: HandlerPlan) -> dict[str, object] | None:
    form_parameters = tuple(
        parameter
        for parameter in handler_plan.parameters
        if parameter.source in {"form", "file"}
    )
    if form_parameters:
        return _form_request_body(form_parameters)

    for parameter in handler_plan.parameters:
        if parameter.source != "body":
            continue

        body: dict[str, object] = {
            "content": {
                "application/json": {
                    "schema": parameter_schema(parameter),
                }
            }
        }
        if parameter.description:
            body["description"] = parameter.description
        if parameter_required(parameter):
            body["required"] = True
        return body
    return None


def _form_request_body(parameters: tuple[BoundParameter, ...]) -> dict[str, object]:
    properties: dict[str, object] = {}
    required: list[str] = []
    descriptions: list[str] = []
    has_file = False
    for parameter in parameters:
        properties[parameter.request_name] = parameter_schema(parameter)
        if parameter.source == "file":
            has_file = True
        if parameter.description:
            descriptions.append(f"{parameter.request_name}: {parameter.description}")
        if parameter_required(parameter):
            required.append(parameter.request_name)

    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    body: dict[str, object] = {
        "content": {
            (
                "multipart/form-data"
                if has_file
                else "application/x-www-form-urlencoded"
            ): {"schema": schema}
        }
    }
    if descriptions:
        body["description"] = "\n".join(descriptions)
    if required:
        body["required"] = True
    return body


def _responses(route: RouteDefinition) -> dict[str, object]:
    annotation = _return_annotation(route)
    if annotation is None or annotation is type(None):
        return {"204": {"description": "No Content"}}

    content = _response_content(annotation)
    response: dict[str, object] = {"description": "Successful Response"}
    if content is not None:
        response["content"] = content
    return {"200": response}


def _response_content(annotation: object) -> dict[str, object] | None:
    if annotation is Signature.empty:
        return None

    stripped = strip_optional(annotation)
    if isinstance(stripped, type) and issubclass(stripped, Response):
        return None
    if stripped is Request:
        return None
    if stripped is str:
        return {"text/plain": {"schema": {"type": "string"}}}
    if stripped is bytes:
        return {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"},
            }
        }
    return {"application/json": {"schema": annotation_schema(annotation)}}


def _return_annotation(route: RouteDefinition) -> object:
    try:
        return get_type_hints(route.handler).get("return", Signature.empty)
    except NameError:
        return route.handler.__annotations__.get("return", Signature.empty)


def _summary(route: RouteDefinition) -> str:
    summary = route.metadata.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return route.name.replace("_", " ").strip().title() or route.name


def _operation_id(route: RouteDefinition, seen: set[str]) -> str:
    explicit = route.metadata.get("operation_id")
    base = explicit if isinstance(explicit, str) and explicit.strip() else route.name
    candidate = _identifier(base)
    if candidate not in seen:
        seen.add(candidate)
        return candidate

    prefix = candidate
    index = 2
    while f"{prefix}_{index}" in seen:
        index += 1
    candidate = f"{prefix}_{index}"
    seen.add(candidate)
    return candidate


def _identifier(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char == "_" else "_" for char in value)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "operation"


def _string_list_metadata(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _openapi_path(pattern: RoutePattern) -> str:
    if not pattern.segments:
        return "/"

    parts: list[str] = []
    for segment in pattern.segments:
        if isinstance(segment, StaticSegment):
            parts.append(segment.value)
        elif isinstance(segment, ParamSegment):
            parts.append(f"{{{segment.name}}}")
    return "/" + "/".join(parts)
