"""Shared execution path for routes exposed as actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from inspect import Signature
from types import UnionType
from typing import Literal, Protocol, Union, get_args, get_origin
from urllib.parse import quote, urlencode

from quater._finalize import (
    add_request_finalizer,
    close_request_finalizers,
    move_request_finalizers_to_response,
)
from quater.actions.approval import (
    action_arguments_hash,
    require_action_approval,
)
from quater.core import RouteDefinition
from quater.datastructures import encode_cookie_header
from quater.exceptions import BadRequestError
from quater.middleware import MiddlewareStack, compile_middleware_pipeline
from quater.params import BoundParameter, HandlerPlan
from quater.request import Request
from quater.response import Response
from quater.routing import ParamSegment, RoutePattern
from quater.typing import ActionApproval, RequestEntrypoint

ActionExecutionSource = Literal["mcp", "cli"]


class ExecutableAction(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def route(self) -> RouteDefinition: ...

    @property
    def pattern(self) -> RoutePattern: ...

    @property
    def handler_plan(self) -> HandlerPlan: ...


@dataclass(slots=True, frozen=True)
class PreparedActionCall:
    action: str
    source: ActionExecutionSource
    request: Request
    path_params: Mapping[str, object]
    bound_arguments: Mapping[str, object]
    arguments_hash: str


@dataclass(slots=True, frozen=True)
class ActionPreflightResult:
    action: str
    source: ActionExecutionSource
    entrypoint: RequestEntrypoint
    method: str
    path: str
    arguments_hash: str
    needs_approval: bool
    approval_token_provided: bool
    subject: str | None

    @property
    def approval_required(self) -> bool:
        return self.needs_approval and not self.approval_token_provided


@dataclass(slots=True, frozen=True)
class _ActionRequestParts:
    path_params: dict[str, object]
    query_string: str
    body: bytes
    content_type: str | None
    headers: tuple[tuple[str, str], ...]
    cookies: tuple[tuple[str, str], ...]


async def execute_action(
    action: ExecutableAction,
    request: Request,
    arguments: Mapping[str, object],
    *,
    source: ActionExecutionSource,
    global_stack: MiddlewareStack | None = None,
    approval_hook: ActionApproval | None = None,
    approval_token: str | None = None,
    debug: bool = False,
) -> Response:
    prepared = await prepare_action_call(action, request, arguments, source=source)
    if action.route.needs_approval:
        await require_action_approval(
            approval_hook,
            action=action.name,
            arguments_hash=prepared.arguments_hash,
            token=approval_token,
            auth=prepared.request.auth,
            context=prepared.request.context,
        )

    async def endpoint(
        action_request: Request,
        path_params: Mapping[str, object],
    ) -> Response:
        return await action.handler_plan.call_response(action_request, path_params)

    pipeline = compile_middleware_pipeline(
        endpoint,
        global_stack=global_stack or MiddlewareStack(),
        route_stack=action.route.middleware,
        debug=debug,
        handle_unhandled_exceptions=False,
    )
    try:
        response = await pipeline(prepared.request, prepared.path_params)
    except BaseException:
        await close_request_finalizers(prepared.request)
        raise
    if prepared.request._mark_request_resources_deferred():
        add_request_finalizer(
            prepared.request,
            prepared.request._aclose_request_resources,
        )
    return move_request_finalizers_to_response(prepared.request, response)


async def preflight_action(
    action: ExecutableAction,
    request: Request,
    arguments: Mapping[str, object],
    *,
    source: ActionExecutionSource,
    approval_token: str | None = None,
) -> ActionPreflightResult:
    prepared = await prepare_action_call(action, request, arguments, source=source)
    return ActionPreflightResult(
        action=action.name,
        source=source,
        entrypoint=prepared.request.context.entrypoint,
        method=prepared.request.method,
        path=prepared.request.path,
        arguments_hash=prepared.arguments_hash,
        needs_approval=action.route.needs_approval,
        approval_token_provided=approval_token is not None,
        subject=(
            prepared.request.auth.subject if prepared.request.auth is not None else None
        ),
    )


async def prepare_action_call(
    action: ExecutableAction,
    request: Request,
    arguments: Mapping[str, object],
    *,
    source: ActionExecutionSource,
) -> PreparedActionCall:
    parts = _build_request_parts(action, arguments)
    context = replace(
        request.context,
        source=source,
        tool_name=action.name if source == "mcp" else None,
        action_name=action.name,
    )
    action_base = Request(
        method=action.route.method,
        path=_render_action_path(action.pattern, parts.path_params),
        scheme=request.scheme,
        headers=(),
        query_string=parts.query_string,
        body=parts.body,
        auth=request.auth,
        client=request.client,
        max_body_size=request.max_body_size,
        max_form_parts=request.max_form_parts,
        max_form_field_size=request.max_form_field_size,
        max_file_size=request.max_file_size,
        upload_spool_size=request.upload_spool_size,
        context=context,
        app=request.app,
    )
    action_request = _request_with_action_headers(
        action_base,
        query_string=parts.query_string,
        body=parts.body,
        content_type=parts.content_type,
        headers=parts.headers,
        cookies=parts.cookies,
    )
    # Authentication ran once on the incoming request and is already on
    # ``request.auth``. Share that request's resource scopes so a session the
    # authenticator opened is the same session the handler resolves, and so it
    # is torn down exactly once.
    action_request._adopt_resource_scope(request)

    bound_arguments = await action.handler_plan.bind(
        action_request,
        parts.path_params,
        include_resources=False,
    )
    return PreparedActionCall(
        action=action.name,
        source=source,
        request=action_request,
        path_params=parts.path_params,
        bound_arguments=bound_arguments,
        arguments_hash=action_arguments_hash(
            action.name,
            _approval_arguments(action.handler_plan.parameters, bound_arguments),
        ),
    )


def _approval_arguments(
    parameters: tuple[BoundParameter, ...],
    bound_arguments: Mapping[str, object],
) -> dict[str, object]:
    return {
        parameter.input_name: bound_arguments[parameter.name]
        for parameter in parameters
        if parameter.source not in {"request", "resource"}
        and parameter.name in bound_arguments
    }


def _build_request_parts(
    action: ExecutableAction,
    arguments: Mapping[str, object],
) -> _ActionRequestParts:
    expected_names = {
        parameter.input_name
        for parameter in action.handler_plan.parameters
        if parameter.source not in {"request", "resource"}
    }
    unknown = sorted(set(arguments) - expected_names)
    if unknown:
        raise BadRequestError(f"Unknown action argument: {unknown[0]}")

    path_params: dict[str, object] = {}
    query_items: list[tuple[str, str]] = []
    header_items: list[tuple[str, str]] = []
    cookie_items: list[tuple[str, str]] = []
    form_items: list[tuple[str, str]] = []
    body_value: object = None
    body_parameter_name: str | None = None
    has_body = False
    has_form = False

    converters = _path_converters(action.pattern)
    for parameter in action.handler_plan.parameters:
        if parameter.source in {"request", "resource"}:
            continue
        if parameter.input_name not in arguments:
            value = _missing_value(parameter)
            if value is _MISSING and parameter.source == "path":
                raise BadRequestError(
                    f"Missing action argument: {parameter.input_name}"
                )
        else:
            value = arguments[parameter.input_name]
            value = _normalize_action_argument(parameter, value)

        if parameter.source == "path":
            path_params[parameter.request_name] = _convert_path_argument(
                parameter.request_name,
                value,
                converters,
            )
        elif parameter.source == "query":
            if value is not _MISSING:
                query_items.append((parameter.request_name, _argument_to_scalar(value)))
        elif parameter.source == "header":
            if value is not _MISSING:
                header_items.append(
                    (
                        parameter.request_name,
                        _argument_to_header(value, parameter.input_name),
                    )
                )
        elif parameter.source == "cookie":
            if value is not _MISSING:
                cookie_items.append(
                    (
                        parameter.request_name,
                        _argument_to_cookie(value, parameter.input_name),
                    )
                )
        elif parameter.source == "form":
            if value is not _MISSING:
                form_items.append((parameter.request_name, _argument_to_scalar(value)))
                has_form = True
        elif parameter.source == "body":
            body_value = value
            body_parameter_name = parameter.input_name
            has_body = True
        elif parameter.source == "file":
            raise BadRequestError("File arguments are not supported for actions")

    body, content_type = _encode_request_parts_body(
        has_body=has_body,
        body_value=body_value,
        body_parameter_name=body_parameter_name,
        has_form=has_form,
        form_items=form_items,
    )

    return _ActionRequestParts(
        path_params=path_params,
        query_string=urlencode(query_items),
        body=body,
        content_type=content_type,
        headers=tuple(header_items),
        cookies=tuple(cookie_items),
    )


_MISSING = object()


def _encode_request_parts_body(
    *,
    has_body: bool,
    body_value: object,
    body_parameter_name: str | None,
    has_form: bool,
    form_items: list[tuple[str, str]],
) -> tuple[bytes, str | None]:
    if has_body:
        if body_value is _MISSING:
            return b"", "application/json"
        return (
            _encode_body_argument(body_value, body_parameter_name),
            "application/json",
        )
    if has_form:
        return (
            urlencode(form_items).encode("utf-8"),
            "application/x-www-form-urlencoded",
        )
    return b"", None


def _missing_value(parameter: BoundParameter) -> object:
    if parameter.default is not Signature.empty:
        return parameter.default if parameter.source == "body" else _MISSING
    if _allows_none(parameter.annotation):
        if parameter.source == "body":
            return None
        return _MISSING
    return _MISSING


def _normalize_action_argument(parameter: BoundParameter, value: object) -> object:
    if value is not None:
        return value
    if parameter.source == "body":
        return value
    if parameter.source in {"query", "header", "cookie", "form"} and _allows_none(
        parameter.annotation
    ):
        return _MISSING
    raise BadRequestError(f"Invalid action argument: {parameter.input_name}")


def _path_converters(pattern: RoutePattern) -> dict[str, ParamSegment]:
    return {
        segment.name: segment
        for segment in pattern.segments
        if isinstance(segment, ParamSegment)
    }


def _convert_path_argument(
    name: str,
    value: object,
    converters: Mapping[str, ParamSegment],
) -> object:
    converter = converters[name]
    try:
        return converter.converter(str(value))
    except ValueError as exc:
        raise BadRequestError(f"Invalid path argument: {name}") from exc


def _argument_to_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _argument_to_header(value: object, name: str) -> str:
    rendered = _argument_to_scalar(value)
    if any(_invalid_header_value_character(char) for char in rendered):
        raise BadRequestError(f"Invalid action argument: {name}")
    return rendered


def _argument_to_cookie(value: object, name: str) -> str:
    rendered = _argument_to_header(value, name)
    if ";" in rendered:
        raise BadRequestError(f"Invalid action argument: {name}")
    return rendered


def _encode_body_argument(value: object, parameter_name: str | None) -> bytes:
    try:
        from quater.serialization import dumps_json

        return dumps_json(value)
    except (TypeError, ValueError) as exc:
        name = parameter_name or "body"
        raise BadRequestError(f"Invalid action argument: {name}") from exc


def _render_action_path(
    pattern: RoutePattern,
    path_params: Mapping[str, object],
) -> str:
    parts: list[str] = []
    for segment in pattern.segments:
        if isinstance(segment, ParamSegment):
            parts.append(quote(str(path_params[segment.name]), safe=""))
        else:
            parts.append(segment.value)
    return "/" + "/".join(parts)


def _request_with_action_headers(
    request: Request,
    *,
    query_string: str,
    body: bytes,
    content_type: str | None,
    headers: tuple[tuple[str, str], ...],
    cookies: tuple[tuple[str, str], ...],
) -> Request:
    if content_type is None and not headers and not cookies:
        return request

    return Request(
        method=request.method,
        path=request.path,
        scheme=request.scheme,
        headers=_action_headers(
            content_type=content_type,
            headers=headers,
            cookies=cookies,
        ),
        query_string=query_string,
        body=body,
        auth=request.auth,
        client=request.client,
        context=request.context,
        app=request.app,
        max_body_size=request.max_body_size,
        max_form_parts=request.max_form_parts,
        max_form_field_size=request.max_form_field_size,
        max_file_size=request.max_file_size,
        upload_spool_size=request.upload_spool_size,
    )


def _action_headers(
    content_type: str | None,
    headers: tuple[tuple[str, str], ...],
    cookies: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    content_type_header = (
        (("content-type", content_type),) if content_type is not None else ()
    )
    cookie_header = (("cookie", _cookie_header(cookies)),) if cookies else ()
    return (*headers, *content_type_header, *cookie_header)


def _cookie_header(cookies: tuple[tuple[str, str], ...]) -> str:
    return encode_cookie_header(cookies)


def _invalid_header_value_character(char: str) -> bool:
    ordinal = ord(char)
    return ordinal == 127 or (ordinal < 32 and char != "\t")


def _allows_none(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return False
    return type(None) in get_args(annotation)
