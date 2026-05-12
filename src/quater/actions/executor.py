"""Shared execution path for routes exposed as actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from inspect import Signature
from types import UnionType
from typing import Literal, Protocol, Union, get_args, get_origin
from urllib.parse import quote, urlencode

from quater.actions.approval import (
    action_arguments_hash,
    require_action_approval,
)
from quater.auth import authenticate_request
from quater.core import RouteDefinition
from quater.exceptions import BadRequestError
from quater.middleware import MiddlewareStack, compile_middleware_pipeline
from quater.params import BoundParameter, HandlerPlan
from quater.request import Request
from quater.response import Response, normalize_response
from quater.routing import ParamSegment, RoutePattern
from quater.typing import ActionApproval, Authenticate, RequestEntrypoint

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


async def execute_action(
    action: ExecutableAction,
    request: Request,
    arguments: Mapping[str, object],
    *,
    source: ActionExecutionSource,
    surface_auth: Authenticate | None = None,
    authenticated_by: Authenticate | None = None,
    approval_hook: ActionApproval | None = None,
    approval_token: str | None = None,
    debug: bool = False,
) -> Response:
    prepared = await prepare_action_call(
        action,
        request,
        arguments,
        source=source,
        surface_auth=surface_auth,
        authenticated_by=authenticated_by,
    )
    if action.route.needs_approval:
        await require_action_approval(
            approval_hook,
            action=action.name,
            arguments=arguments,
            token=approval_token,
            auth=prepared.request.auth,
            context=prepared.request.context,
        )

    async def endpoint(
        action_request: Request,
        _path_params: Mapping[str, object],
    ) -> Response:
        result = await action.handler_plan.handler(
            **_handler_arguments_for_request(
                action.handler_plan,
                prepared.bound_arguments,
                action_request,
            )
        )
        return normalize_response(result)

    pipeline = compile_middleware_pipeline(
        endpoint,
        global_stack=MiddlewareStack(),
        route_stack=action.route.middleware,
        debug=debug,
        handle_unhandled_exceptions=False,
    )
    return await pipeline(prepared.request, prepared.path_params)


def _handler_arguments_for_request(
    handler_plan: HandlerPlan,
    bound_arguments: Mapping[str, object],
    request: Request,
) -> dict[str, object]:
    arguments = dict(bound_arguments)
    for parameter in handler_plan.parameters:
        if parameter.source == "request":
            arguments[parameter.name] = request
    return arguments


async def preflight_action(
    action: ExecutableAction,
    request: Request,
    arguments: Mapping[str, object],
    *,
    source: ActionExecutionSource,
    surface_auth: Authenticate | None = None,
    authenticated_by: Authenticate | None = None,
    approval_token: str | None = None,
) -> ActionPreflightResult:
    prepared = await prepare_action_call(
        action,
        request,
        arguments,
        source=source,
        surface_auth=surface_auth,
        authenticated_by=authenticated_by,
    )
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
    surface_auth: Authenticate | None = None,
    authenticated_by: Authenticate | None = None,
) -> PreparedActionCall:
    path_params, query_string, body = _build_request_parts(action, arguments)
    action_request = Request(
        method=action.route.method,
        path=_render_action_path(action.pattern, path_params),
        scheme=request.scheme,
        headers=request.headers.raw,
        query_string=query_string,
        body=body,
        auth=request.auth,
        client=request.client,
        max_body_size=request.max_body_size,
        context=replace(
            request.context,
            source=source,
            tool_name=action.name if source == "mcp" else None,
            action_name=action.name,
        ),
    )

    surface_authenticated = False
    if request.auth is not None and authenticated_by is not None:
        surface_authenticated = authenticated_by is surface_auth

    if surface_auth is not None and not surface_authenticated:
        await authenticate_request(surface_auth, action_request)
        request.auth = action_request.auth

    route_auth = action.route.auth
    if route_auth is not None:
        await authenticate_request(route_auth, action_request)
        request.auth = action_request.auth

    bound_arguments = await action.handler_plan.bind(action_request, path_params)
    return PreparedActionCall(
        action=action.name,
        source=source,
        request=action_request,
        path_params=path_params,
        bound_arguments=bound_arguments,
        arguments_hash=action_arguments_hash(action.name, arguments),
    )


def _build_request_parts(
    action: ExecutableAction,
    arguments: Mapping[str, object],
) -> tuple[dict[str, object], str, bytes]:
    expected_names = {
        parameter.name
        for parameter in action.handler_plan.parameters
        if parameter.source != "request"
    }
    unknown = sorted(set(arguments) - expected_names)
    if unknown:
        raise BadRequestError(f"Unknown action argument: {unknown[0]}")

    path_params: dict[str, object] = {}
    query_items: list[tuple[str, str]] = []
    body_value: object = None
    body_parameter_name: str | None = None
    has_body = False

    converters = _path_converters(action.pattern)
    for parameter in action.handler_plan.parameters:
        if parameter.source == "request":
            continue
        if parameter.name not in arguments:
            value = _missing_value(parameter)
            if value is _MISSING and parameter.source != "query":
                raise BadRequestError(f"Missing action argument: {parameter.name}")
        else:
            value = arguments[parameter.name]

        if parameter.source == "path":
            path_params[parameter.name] = _convert_path_argument(
                parameter.name,
                value,
                converters,
            )
        elif parameter.source == "query":
            if value is not _MISSING:
                query_items.append((parameter.name, _argument_to_query(value)))
        elif parameter.source == "body":
            body_value = value
            body_parameter_name = parameter.name
            has_body = True

    return (
        path_params,
        urlencode(query_items),
        _encode_body_argument(body_value, body_parameter_name) if has_body else b"",
    )


_MISSING = object()


def _missing_value(parameter: BoundParameter) -> object:
    if parameter.default is not Signature.empty:
        return parameter.default
    if _allows_none(parameter.annotation):
        if parameter.source == "body":
            return None
        return _MISSING
    return _MISSING


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


def _argument_to_query(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


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


def _allows_none(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return False
    return type(None) in get_args(annotation)
