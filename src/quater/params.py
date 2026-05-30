"""Handler parameter binding."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from types import UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from quater._finalize import add_request_finalizer
from quater._parameters import ParameterMarker
from quater.core import Handler
from quater.dependencies import Resource, ResourceMap
from quater.exceptions import BadRequestError, RequestJSONError, RouteBindingError
from quater.request import Request
from quater.response import Response

_EMPTY = inspect.Signature.empty
ParameterSource = Literal[
    "request",
    "resource",
    "path",
    "query",
    "body",
    "form",
    "file",
    "header",
    "cookie",
]


@dataclass(slots=True, frozen=True)
class BoundParameter:
    name: str
    source: ParameterSource
    request_name: str
    input_name: str
    annotation: object
    default: object
    description: str | None = None
    resource: Resource | None = None


@dataclass(slots=True, frozen=True)
class HandlerPlan:
    handler: Handler
    parameters: tuple[BoundParameter, ...]

    async def bind(
        self,
        request: Request,
        path_params: Mapping[str, object],
        *,
        include_resources: bool = True,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {}
        for parameter in self.parameters:
            if parameter.source == "request":
                kwargs[parameter.name] = request
            elif parameter.source == "resource":
                if not include_resources:
                    continue
                if parameter.resource is None:
                    raise RuntimeError("Injected parameter is missing its resource")
                kwargs[parameter.name] = await _bind_resource_parameter(
                    parameter,
                    request,
                )
            elif parameter.source == "path":
                kwargs[parameter.name] = path_params[parameter.request_name]
            elif parameter.source == "query":
                kwargs[parameter.name] = _bind_query_parameter(request, parameter)
            elif parameter.source == "header":
                kwargs[parameter.name] = _bind_header_parameter(request, parameter)
            elif parameter.source == "cookie":
                kwargs[parameter.name] = _bind_cookie_parameter(request, parameter)
            elif parameter.source == "body":
                kwargs[parameter.name] = await _bind_body_parameter(request, parameter)
            elif parameter.source == "form":
                kwargs[parameter.name] = await _bind_form_parameter(request, parameter)
            elif parameter.source == "file":
                kwargs[parameter.name] = await _bind_file_parameter(request, parameter)

        return kwargs

    async def call(self, request: Request, path_params: Mapping[str, object]) -> object:
        if not any(parameter.source == "resource" for parameter in self.parameters):
            return await self.handler(**await self.bind(request, path_params))

        try:
            kwargs = await self.bind(request, path_params)
            return await self.handler(**kwargs)
        finally:
            await request._aclose_resources()

    async def call_response(
        self,
        request: Request,
        path_params: Mapping[str, object],
    ) -> Response:
        from quater.response import normalize_response

        if not any(parameter.source == "resource" for parameter in self.parameters):
            return normalize_response(
                await self.handler(**await self.bind(request, path_params))
            )

        try:
            kwargs = await self.bind(request, path_params)
            response = normalize_response(await self.handler(**kwargs))
        except BaseException:
            await request._aclose_resources()
            raise

        if request.has_open_resources:
            add_request_finalizer(request, request._aclose_resources)
        return response


def build_handler_plan(
    handler: Handler,
    *,
    path_param_names: frozenset[str],
    inject: ResourceMap | None = None,
) -> HandlerPlan:
    if not inspect.iscoroutinefunction(handler):
        raise RouteBindingError("Route handlers must be async functions")

    signature = inspect.signature(handler)
    try:
        type_hints = get_type_hints(handler, include_extras=True)
    except (NameError, TypeError):
        type_hints = handler.__annotations__
    body_parameters = 0
    form_parameters = 0
    file_parameters = 0
    resources = _normalize_resources(inject)
    parameters: list[BoundParameter] = []
    seen_names: set[str] = set()

    for name, parameter in signature.parameters.items():
        seen_names.add(name)
        if parameter.kind not in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            raise RouteBindingError(
                f"Unsupported parameter kind for {name!r}: {parameter.kind!s}"
            )

        annotation, annotation_marker, annotation_resource = _annotation_and_markers(
            type_hints.get(name, parameter.annotation)
        )
        raw_default, default_marker = _default_and_marker(parameter.default)
        if isinstance(raw_default, Resource):
            raise RouteBindingError(
                f"Resource for {name!r} must be declared in inject= or in the "
                "type annotation (Annotated[T, resource]), not as a default value"
            )
        resource = resources.get(name)
        if annotation_resource is not None:
            if resource is not None:
                raise RouteBindingError(
                    f"Injected parameter {name!r} is declared both in inject= "
                    "and in its type annotation"
                )
            resource = annotation_resource
        marker = _resolve_marker(name, annotation_marker, default_marker)
        default = _resolve_default(name, raw_default, marker)
        source = _parameter_source(
            name,
            annotation,
            marker,
            path_param_names,
            resource=resource,
        )
        request_name = _parameter_request_name(name, source, marker)
        input_name = _parameter_input_name(name, source, marker)
        _validate_bound_parameter(
            name,
            source=source,
            request_name=request_name,
            input_name=input_name,
            default=default,
            annotation=annotation,
            path_param_names=path_param_names,
            resource=resource,
            marker=marker,
        )
        if source == "body":
            body_parameters += 1
            if body_parameters > 1:
                raise RouteBindingError("Only one body parameter is supported")
        elif source == "form":
            form_parameters += 1
        elif source == "file":
            file_parameters += 1

        parameters.append(
            BoundParameter(
                name=name,
                source=source,
                request_name=request_name,
                input_name=input_name,
                annotation=annotation,
                default=default,
                description=marker.description if marker is not None else None,
                resource=resource,
            )
        )

    if body_parameters and (form_parameters or file_parameters):
        raise RouteBindingError(
            "JSON body parameters cannot be combined with form or file parameters"
        )
    _validate_all_resources_are_used(resources, seen_names)
    _validate_parameter_collisions(parameters)
    return HandlerPlan(handler=handler, parameters=tuple(parameters))


def _parameter_source(
    name: str,
    annotation: object,
    marker: ParameterMarker | None,
    path_param_names: frozenset[str],
    *,
    resource: Resource | None,
) -> ParameterSource:
    if resource is not None:
        if name == "request" or annotation is Request:
            raise RouteBindingError("Request objects cannot be injected as resources")
        if marker is not None:
            raise RouteBindingError(
                f"Injected parameter {name!r} cannot use a parameter marker"
            )
        if name in path_param_names:
            raise RouteBindingError(
                f"Injected parameter {name!r} conflicts with a path parameter"
            )
        return "resource"
    if name == "request" or annotation is Request:
        if marker is not None:
            raise RouteBindingError(
                f"Request parameter {name!r} cannot use a parameter marker"
            )
        return "request"
    if marker is not None:
        if name in path_param_names and marker.source != "path":
            raise RouteBindingError(
                f"Path parameter {name!r} cannot use {marker.source} binding"
            )
        return marker.source
    if name in path_param_names:
        return "path"
    if _is_query_type(annotation):
        return "query"
    return "body"


def _parameter_request_name(
    name: str,
    source: ParameterSource,
    marker: ParameterMarker | None,
) -> str:
    if marker is None:
        return name
    if source == "header" and marker.alias is None and marker.convert_underscores:
        return name.replace("_", "-")
    return marker.alias or name


def _parameter_input_name(
    name: str,
    source: ParameterSource,
    marker: ParameterMarker | None,
) -> str:
    if source == "body" and marker is not None and marker.alias is not None:
        return marker.alias
    return name


def _bind_query_parameter(request: Request, parameter: BoundParameter) -> object:
    value = request.query.get(parameter.request_name)
    if value is None:
        return _missing_request_value(parameter, label="query parameter")
    return convert_scalar_value(
        value,
        parameter.annotation,
        parameter.request_name,
        source="query parameter",
    )


def _bind_header_parameter(request: Request, parameter: BoundParameter) -> object:
    value = request.headers.get(parameter.request_name)
    if value is None:
        return _missing_request_value(parameter, label="header")
    return convert_scalar_value(
        value,
        parameter.annotation,
        parameter.request_name,
        source="header",
    )


def _bind_cookie_parameter(request: Request, parameter: BoundParameter) -> object:
    value = request.cookies.get(parameter.request_name)
    if value is None:
        return _missing_request_value(parameter, label="cookie")
    return convert_scalar_value(
        value,
        parameter.annotation,
        parameter.request_name,
        source="cookie",
    )


async def _bind_form_parameter(request: Request, parameter: BoundParameter) -> object:
    value = (await request.form()).get(parameter.request_name)
    if value is None:
        return _missing_request_value(parameter, label="form field")
    return convert_scalar_value(
        value,
        parameter.annotation,
        parameter.request_name,
        source="form field",
    )


def _missing_request_value(parameter: BoundParameter, *, label: str) -> object:
    if parameter.default is not _EMPTY:
        return parameter.default
    if _allows_none(parameter.annotation):
        return None
    raise BadRequestError(f"Missing required {label}: {parameter.request_name}")


async def _bind_body_parameter(request: Request, parameter: BoundParameter) -> object:
    annotation = parameter.annotation
    if _uses_generic_json(annotation):
        return await request.json()

    from quater.serialization import JSONValidationError, loads_json_as

    try:
        return loads_json_as(await request.body(), annotation)
    except RequestJSONError:
        raise
    except (JSONValidationError, TypeError) as exc:
        raise BadRequestError(
            f"Invalid JSON body for parameter: {parameter.name}"
        ) from exc


async def _bind_file_parameter(request: Request, parameter: BoundParameter) -> object:
    files = (await request.form()).get_files(parameter.request_name)
    if not files:
        return _missing_request_value(parameter, label="file")

    if _is_upload_file_list(parameter.annotation):
        return list(files)
    if _is_bytes_list(parameter.annotation):
        return [await _read_upload_file(file) for file in files]

    if len(files) > 1:
        raise BadRequestError(
            f"Multiple files received for parameter: {parameter.name}"
        )

    file = files[0]
    if _is_upload_file_annotation(parameter.annotation):
        return file
    if _is_bytes_annotation(parameter.annotation):
        return await _read_upload_file(file)

    raise BadRequestError(f"Invalid file parameter: {parameter.name}")


async def _read_upload_file(file: object) -> bytes:
    from quater.formdata import UploadFile

    if not isinstance(file, UploadFile):
        raise RuntimeError("File parameter did not resolve to UploadFile")
    await file.seek(0)
    return await file.read()


def _uses_generic_json(annotation: object) -> bool:
    return annotation in {_EMPTY, Any, object, dict, list}


def _is_query_type(annotation: object) -> bool:
    if annotation is _EMPTY:
        return True
    annotation = _strip_optional(annotation)
    return annotation in {str, int, float, bool}


def _is_upload_file_annotation(annotation: object) -> bool:
    from quater.formdata import UploadFile

    return _strip_optional(annotation) is UploadFile


def _is_bytes_annotation(annotation: object) -> bool:
    return _strip_optional(annotation) is bytes


def _is_upload_file_list(annotation: object) -> bool:
    from quater.formdata import UploadFile

    stripped = _strip_optional(annotation)
    return get_origin(stripped) is list and get_args(stripped) == (UploadFile,)


def _is_bytes_list(annotation: object) -> bool:
    stripped = _strip_optional(annotation)
    return get_origin(stripped) is list and get_args(stripped) == (bytes,)


def convert_scalar_value(
    value: str,
    annotation: object,
    name: str,
    *,
    source: str,
) -> object:
    annotation = _strip_optional(annotation)
    if annotation is _EMPTY or annotation is str:
        return value
    if annotation is int:
        try:
            return int(value)
        except ValueError as exc:
            raise BadRequestError(f"Invalid integer {source}: {name}") from exc
    if annotation is float:
        try:
            return float(value)
        except ValueError as exc:
            raise BadRequestError(f"Invalid float {source}: {name}") from exc
    if annotation is bool:
        return _parse_bool(value, name, source=source)
    return value


def _parse_bool(value: str, name: str, *, source: str) -> bool:
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise BadRequestError(f"Invalid boolean {source}: {name}")


def _strip_optional(annotation: object) -> object:
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return annotation
    args = tuple(arg for arg in get_args(annotation) if arg is not type(None))
    return args[0] if len(args) == 1 else annotation


def _allows_none(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return False
    return type(None) in get_args(annotation)


def _annotation_and_markers(
    annotation: object,
) -> tuple[object, ParameterMarker | None, Resource | None]:
    if get_origin(annotation) is not Annotated:
        return annotation, None, None

    args = get_args(annotation)
    if not args:
        return annotation, None, None

    marker: ParameterMarker | None = None
    resource: Resource | None = None
    for metadata in args[1:]:
        if isinstance(metadata, ParameterMarker):
            if marker is not None:
                raise RouteBindingError("Only one parameter marker is supported")
            marker = metadata
        elif isinstance(metadata, Resource):
            if resource is not None:
                raise RouteBindingError(
                    "Only one resource is supported in a type annotation"
                )
            resource = metadata
    return args[0], marker, resource


def _default_and_marker(value: object) -> tuple[object, ParameterMarker | None]:
    if isinstance(value, ParameterMarker):
        return _EMPTY, value
    return value, None


def _resolve_marker(
    name: str,
    annotation_marker: ParameterMarker | None,
    default_marker: ParameterMarker | None,
) -> ParameterMarker | None:
    if annotation_marker is not None and default_marker is not None:
        raise RouteBindingError(
            f"Parameter {name!r} cannot use markers in both Annotated and default"
        )
    return annotation_marker or default_marker


def _resolve_default(
    name: str,
    default: object,
    marker: ParameterMarker | None,
) -> object:
    if marker is None:
        return default
    if marker.default is not _EMPTY and default is not _EMPTY:
        raise RouteBindingError(f"Parameter {name!r} cannot define a default twice")
    if marker.default is not _EMPTY:
        return marker.default
    return default


def _validate_bound_parameter(
    name: str,
    *,
    source: ParameterSource,
    request_name: str,
    input_name: str,
    default: object,
    annotation: object,
    path_param_names: frozenset[str],
    resource: Resource | None,
    marker: ParameterMarker | None,
) -> None:
    if source == "request":
        return
    if source == "resource":
        if resource is None:
            raise RouteBindingError(f"Injected parameter {name!r} has no resource")
        if default is not _EMPTY:
            raise RouteBindingError(
                f"Injected parameter {name!r} cannot define a default"
            )
        if marker is not None:
            raise RouteBindingError(
                f"Injected parameter {name!r} cannot use a parameter marker"
            )
        return
    if source == "path":
        if request_name not in path_param_names:
            raise RouteBindingError(
                f"Path parameter {name!r} does not match route path"
            )
        if default is not _EMPTY:
            raise RouteBindingError(f"Path parameter {name!r} cannot define a default")
        return
    if source == "header":
        _validate_header_name(request_name)
    elif source == "cookie":
        _validate_cookie_name(request_name)
    elif source == "body" and not input_name.isidentifier():
        raise RouteBindingError(f"Body parameter {name!r} must use an identifier alias")

    if annotation is Request:
        raise RouteBindingError(
            f"Request parameter {name!r} cannot be bound from {source}"
        )
    if source in {"query", "header", "cookie", "form"}:
        _validate_scalar_annotation(name, source=source, annotation=annotation)
    if source == "file":
        _validate_file_annotation(name, annotation)


def _validate_header_name(name: str) -> None:
    if not name or not all(_is_header_name_char(char) for char in name):
        raise RouteBindingError(f"Invalid header parameter name: {name!r}")


def _is_header_name_char(char: str) -> bool:
    ordinal = ord(char)
    if ordinal > 127:
        return False
    return char.isalnum() or char in "!#$%&'*+-.^_`|~"


def _validate_cookie_name(name: str) -> None:
    if not name or not all(_is_header_name_char(char) for char in name):
        raise RouteBindingError(f"Invalid cookie parameter name: {name!r}")


def _validate_scalar_annotation(
    name: str,
    *,
    source: ParameterSource,
    annotation: object,
) -> None:
    stripped = _strip_optional(annotation)
    if stripped in {_EMPTY, str, int, float, bool}:
        return
    raise RouteBindingError(
        f"{source.title()} parameter {name!r} must use str, int, float, or bool"
    )


def _validate_file_annotation(name: str, annotation: object) -> None:
    if (
        _is_upload_file_annotation(annotation)
        or _is_bytes_annotation(annotation)
        or _is_upload_file_list(annotation)
        or _is_bytes_list(annotation)
    ):
        return
    raise RouteBindingError(
        f"File parameter {name!r} must use UploadFile, bytes, "
        "list[UploadFile], or list[bytes]"
    )


def _validate_parameter_collisions(parameters: list[BoundParameter]) -> None:
    action_names: dict[str, str] = {}
    request_names: dict[tuple[ParameterSource, str], str] = {}

    for parameter in parameters:
        if parameter.source in {"request", "resource"}:
            continue

        existing_action_name = action_names.get(parameter.input_name)
        if existing_action_name is not None:
            raise RouteBindingError(
                "Duplicate action argument name "
                f"{parameter.input_name!r} for parameters "
                f"{existing_action_name!r} and {parameter.name!r}"
            )
        action_names[parameter.input_name] = parameter.name

        if parameter.source not in {
            "path",
            "query",
            "header",
            "cookie",
            "form",
            "file",
        }:
            continue
        request_key = _request_name_collision_key(parameter)
        existing_request_name = request_names.get(request_key)
        if existing_request_name is not None:
            raise RouteBindingError(
                "Duplicate request parameter name "
                f"{parameter.request_name!r} for parameters "
                f"{existing_request_name!r} and {parameter.name!r}"
            )
        request_names[request_key] = parameter.name


def _request_name_collision_key(
    parameter: BoundParameter,
) -> tuple[ParameterSource, str]:
    if parameter.source == "header":
        return parameter.source, parameter.request_name.lower()
    if parameter.source in {"form", "file"}:
        return "form", parameter.request_name
    return parameter.source, parameter.request_name


async def _bind_resource_parameter(
    parameter: BoundParameter,
    request: Request,
) -> object:
    resource = parameter.resource
    if resource is None:
        raise RuntimeError("Injected parameter is missing its resource")
    scope = request.resources
    cache = scope.cache
    cache_key = id(resource)
    if cache_key not in cache:
        cache[cache_key] = await resource.resolve(request, scope.stack())
    return cache[cache_key]


def _normalize_resources(inject: ResourceMap | None) -> dict[str, Resource]:
    if inject is None:
        return {}
    resources: dict[str, Resource] = {}
    for name, resource in inject.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise RouteBindingError(f"Invalid injected parameter name: {name!r}")
        if not isinstance(resource, Resource):
            raise TypeError("inject values must be Resource instances")
        resources[name] = resource
    return resources


def _validate_all_resources_are_used(
    resources: Mapping[str, Resource],
    seen_names: set[str],
) -> None:
    for name in resources:
        if name not in seen_names:
            raise RouteBindingError(
                f"Injected parameter {name!r} does not exist on the handler"
            )
