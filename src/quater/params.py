"""Handler parameter binding."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from types import UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from quater._parameters import (
    Body,
    Cookie,
    File,
    Form,
    Header,
    ParameterMarker,
    Path,
    Query,
)
from quater.core import Handler
from quater.dependencies import Resource, ResourceMap, validate_resource
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
    resource: Resource[Any] | None = None


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

    async def call_response(
        self,
        request: Request,
        path_params: Mapping[str, object],
    ) -> Response:
        from quater.response import normalize_response

        try:
            kwargs = await self.bind(request, path_params)
            response = normalize_response(await self.handler(**kwargs))
        except BaseException as exc:
            await request._aexit_resources_for_error(exc)
            raise

        return response


def build_handler_plan(
    handler: Handler,
    *,
    path_param_names: frozenset[str],
    path_param_converters: Mapping[str, str] | None = None,
    inject: ResourceMap | None = None,
) -> HandlerPlan:
    if not inspect.iscoroutinefunction(handler):
        raise RouteBindingError("Route handlers must be async functions")

    signature = inspect.signature(handler)
    body_parameters = 0
    form_parameters = 0
    file_parameters = 0
    resources = _normalize_resources(inject)
    converters = _normalize_path_param_converters(
        path_param_names,
        path_param_converters,
    )
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

        raw_default, default_marker = _default_and_marker(parameter.default)
        if isinstance(raw_default, Resource):
            raise RouteBindingError(
                f"Resource for {name!r} must be declared in inject= or in the "
                "type annotation (Annotated[T, resource]), not as a default value"
            )
        resource = resources.get(name)
        raw_annotation = _resolve_handler_parameter_annotation(
            handler,
            parameter,
            resource=resource,
        )
        annotation, annotation_marker, annotation_resource = _annotation_and_markers(
            raw_annotation
        )
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
            path_param_converters=converters,
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
    for bound_parameter in parameters:
        if bound_parameter.source == "resource" and bound_parameter.resource:
            validate_resource(bound_parameter.resource)
    return HandlerPlan(handler=handler, parameters=tuple(parameters))


def _resolve_handler_parameter_annotation(
    handler: Handler,
    parameter: inspect.Parameter,
    *,
    resource: Resource[Any] | None,
) -> object:
    annotation = parameter.annotation
    if annotation is _EMPTY:
        return annotation
    proxy = _AnnotationProxy()
    proxy.__annotations__ = {parameter.name: annotation}
    globalns = _callable_globalns(handler)
    try:
        return get_type_hints(
            proxy,
            globalns=globalns,
            include_extras=True,
        )[parameter.name]
    except NameError as exc:
        if resource is not None or parameter.name == "request":
            return annotation
        raise _unresolved_handler_annotation_error(handler, parameter, exc) from exc
    except (SyntaxError, TypeError) as exc:
        raise _unresolved_handler_annotation_error(handler, parameter, exc) from exc


def _unresolved_handler_annotation_error(
    handler: Handler,
    parameter: inspect.Parameter,
    exc: Exception,
) -> RouteBindingError:
    handler_name = getattr(
        handler,
        "__qualname__",
        getattr(handler, "__name__", "handler"),
    )
    return RouteBindingError(
        f"Handler parameter {parameter.name!r} on {handler_name!r} has "
        f"annotation {parameter.annotation!r} that could not be resolved: {exc}. "
        "Define referenced types, Resources, and Annotated aliases at module scope, "
        "or use inject= for app-owned resource parameters."
    )


def _callable_globalns(handler: Handler) -> dict[str, object]:
    target = inspect.unwrap(handler)
    globalns = getattr(target, "__globals__", None)
    if isinstance(globalns, dict):
        return globalns
    return {}


class _AnnotationProxy:
    __annotations__: dict[str, object]


def _parameter_source(
    name: str,
    annotation: object,
    marker: ParameterMarker | None,
    path_param_names: frozenset[str],
    *,
    resource: Resource[Any] | None,
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
    # Scalar params bind from the query string on every surface, but MCP and CLI
    # callers pass them as plain arguments — "query parameter" would be wrong
    # there, so neutralize the wording off the HTTP surface.
    label = "query parameter" if request.context.source == "api" else "parameter"
    value = request.query.get(parameter.request_name)
    if value is None:
        return _missing_request_value(parameter, label=label)
    return convert_scalar_value(
        value,
        parameter.annotation,
        parameter.request_name,
        source=label,
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
    body = await request.body()
    if body == b"":
        return _missing_request_value(parameter, label="body parameter")

    if _uses_generic_json(annotation):
        from quater.serialization import loads_json

        return loads_json(body)

    from quater.serialization import JSONValidationError, loads_json_as

    try:
        return loads_json_as(body, annotation)
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
    return annotation in {_EMPTY, Any, object}


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
            parsed = float(value)
        except ValueError as exc:
            raise BadRequestError(f"Invalid float {source}: {name}") from exc
        if not isfinite(parsed):
            raise BadRequestError(f"Invalid float {source}: {name}")
        return parsed
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
) -> tuple[object, ParameterMarker | None, Resource[Any] | None]:
    if isinstance(annotation, str):
        parsed = _string_annotation_and_markers(annotation)
        if parsed is not None:
            return parsed

    if get_origin(annotation) is not Annotated:
        return annotation, None, None

    args = get_args(annotation)
    if not args:
        return annotation, None, None

    marker: ParameterMarker | None = None
    resource: Resource[Any] | None = None
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


def _string_annotation_and_markers(
    annotation: str,
) -> tuple[object, ParameterMarker | None, Resource[Any] | None] | None:
    try:
        node = ast.parse(annotation, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Subscript):
        return None
    if ast.unparse(node.value) not in {
        "Annotated",
        "typing.Annotated",
        "typing_extensions.Annotated",
    }:
        return None
    if not isinstance(node.slice, ast.Tuple):
        return None
    args = tuple(node.slice.elts)

    marker: ParameterMarker | None = None
    for metadata in args[1:]:
        parsed_marker = _string_parameter_marker(metadata)
        if parsed_marker is None:
            continue
        if marker is not None:
            raise RouteBindingError("Only one parameter marker is supported")
        marker = parsed_marker

    return _normalize_string_path_annotation(ast.unparse(args[0])), marker, None


def _string_parameter_marker(node: ast.AST) -> ParameterMarker | None:
    if not isinstance(node, ast.Call):
        return None
    factory = _STRING_PARAMETER_MARKERS.get(ast.unparse(node.func))
    if factory is None:
        return None
    try:
        args = [ast.literal_eval(arg) for arg in node.args]
        kwargs = {
            keyword.arg: ast.literal_eval(keyword.value)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        marker = factory(*args, **kwargs)
    except (TypeError, ValueError):
        return None
    return cast(ParameterMarker, marker)


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
    path_param_converters: Mapping[str, str],
    resource: Resource[Any] | None,
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
        _validate_path_parameter_annotation(
            name,
            request_name=request_name,
            annotation=annotation,
            converter_name=path_param_converters.get(request_name, "str"),
        )
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


def _normalize_path_param_converters(
    path_param_names: frozenset[str],
    path_param_converters: Mapping[str, str] | None,
) -> Mapping[str, str]:
    if path_param_converters is not None:
        return path_param_converters
    return {name: "str" for name in path_param_names}


def _validate_path_parameter_annotation(
    name: str,
    *,
    request_name: str,
    annotation: object,
    converter_name: str,
) -> None:
    stripped = _normalize_path_annotation(annotation)
    if stripped in {_EMPTY, Any, object}:
        return

    expected_annotation = _PATH_CONVERTER_ANNOTATIONS[converter_name]
    if stripped is expected_annotation:
        return

    subject = f"Path parameter {name!r}"
    if request_name != name:
        subject = f"{subject} for route parameter {request_name!r}"
    route_segment = _path_segment_label(request_name, converter_name)
    message = (
        f"{subject} is annotated as {_annotation_label(stripped)} but route path "
        f"uses {route_segment}."
    )
    expected_segment = _path_segment_for_annotation(request_name, stripped)
    if expected_segment is not None:
        message = f"{message} Use {expected_segment} or change the annotation."
    else:
        message = (
            f"{message} Path parameter annotations must match a supported route "
            "converter."
        )
    raise RouteBindingError(message)


def _normalize_path_annotation(annotation: object) -> object:
    stripped = _strip_optional(annotation)
    if not isinstance(stripped, str):
        return stripped
    return _normalize_string_path_annotation(stripped)


def _normalize_string_path_annotation(annotation: str) -> object:
    normalized = annotation.replace(" ", "")
    for prefix in ("Optional[", "typing.Optional["):
        if normalized.startswith(prefix) and normalized.endswith("]"):
            return _normalize_string_path_annotation(normalized[len(prefix) : -1])

    if "|" in normalized:
        parts = [
            part
            for part in normalized.split("|")
            if part not in {"None", "NoneType", "type(None)"}
        ]
        if len(parts) == 1:
            return _normalize_string_path_annotation(parts[0])

    return {
        "Any": Any,
        "typing.Any": Any,
        "object": object,
        "builtins.object": object,
        "str": str,
        "builtins.str": str,
        "int": int,
        "builtins.int": int,
    }.get(normalized, annotation)


def _path_segment_label(name: str, converter_name: str) -> str:
    if converter_name == "str":
        return f"{{{name}}}"
    return f"{{{name}:{converter_name}}}"


def _path_segment_for_annotation(name: str, annotation: object) -> str | None:
    if annotation is str:
        return _path_segment_label(name, "str")
    if annotation is int:
        return _path_segment_label(name, "int")
    return None


def _annotation_label(annotation: object) -> str:
    origin = get_origin(annotation)
    if origin in {UnionType, Union}:
        return " | ".join(_annotation_label(arg) for arg in get_args(annotation))
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    return repr(annotation)


_PATH_CONVERTER_ANNOTATIONS = {"str": str, "int": int}
_STRING_PARAMETER_MARKERS: Mapping[str, Callable[..., object]] = {
    "Body": Body,
    "Cookie": Cookie,
    "File": File,
    "Form": Form,
    "Header": Header,
    "Path": Path,
    "Query": Query,
    "quater.Body": Body,
    "quater.Cookie": Cookie,
    "quater.File": File,
    "quater.Form": Form,
    "quater.Header": Header,
    "quater.Path": Path,
    "quater.Query": Query,
}


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
    return await request.resolve(resource)


def _normalize_resources(inject: ResourceMap | None) -> dict[str, Resource[Any]]:
    if inject is None:
        return {}
    resources: dict[str, Resource[Any]] = {}
    for name, resource in inject.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise RouteBindingError(f"Invalid injected parameter name: {name!r}")
        if not isinstance(resource, Resource):
            raise TypeError("inject values must be Resource instances")
        resources[name] = resource
    return resources


def _validate_all_resources_are_used(
    resources: Mapping[str, Resource[Any]],
    seen_names: set[str],
) -> None:
    for name in resources:
        if name not in seen_names:
            raise RouteBindingError(
                f"Injected parameter {name!r} does not exist on the handler"
            )
