"""Shared RouteDefinition construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from quater.actions.descriptions import resolve_action_description
from quater.core import Handler, PublicSurfaces, RouteDefinition, normalize_public
from quater.dependencies import Resource, ResourceMap
from quater.exceptions import ConfigurationError
from quater.middleware import (
    AfterMiddleware,
    AroundMiddleware,
    BeforeMiddleware,
    ExceptionHandlerEntry,
    MiddlewareStack,
)
from quater.tools.descriptions import (
    normalize_route_description,
    resolve_tool_description,
)


def build_route_definition(
    method: str,
    path: str,
    handler: Handler,
    *,
    name: str | None = None,
    description: str | None = None,
    tool: bool = False,
    cli: bool = False,
    needs_approval: bool = False,
    public: PublicSurfaces = False,
    inject: ResourceMap | None = None,
    metadata: Mapping[str, Any] | None = None,
    before: Iterable[BeforeMiddleware] = (),
    after: Iterable[AfterMiddleware] = (),
    around: Iterable[AroundMiddleware] = (),
    exception_handlers: Iterable[ExceptionHandlerEntry] = (),
) -> RouteDefinition:
    """Build route metadata shared by application and group registration."""

    route_name = route_name_for(handler, name)
    route_description = resolve_route_description(
        route_name,
        description,
        handler,
        tool=tool,
        cli=cli,
    )
    validate_external_route_options(
        route_name,
        tool=tool,
        cli=cli,
        needs_approval=needs_approval,
    )
    return RouteDefinition(
        method=method.upper(),
        path=path,
        handler=handler,
        name=route_name,
        description=route_description,
        tool=tool,
        cli=cli,
        needs_approval=needs_approval,
        public=normalize_public(
            public,
            tool=tool,
            cli=cli,
            route_name=route_name,
        ),
        inject=dict(inject or {}),
        metadata=dict(metadata or {}),
        middleware=MiddlewareStack.from_parts(
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        ),
    )


def route_name_for(handler: Handler, explicit_name: str | None) -> str:
    if explicit_name is not None:
        return explicit_name
    discovered_name = getattr(handler, "__name__", None)
    return discovered_name if isinstance(discovered_name, str) else "anonymous"


def resolve_route_description(
    route_name: str,
    description: str | None,
    handler: Handler,
    *,
    tool: bool,
    cli: bool,
) -> str | None:
    if tool:
        return resolve_tool_description(route_name, description, handler)
    if cli:
        return resolve_action_description(
            "CLI action",
            route_name,
            description,
            handler,
        )
    return normalize_route_description(description)


def validate_external_route_options(
    route_name: str,
    *,
    tool: bool,
    cli: bool,
    needs_approval: bool,
) -> None:
    if route_name == "anonymous" and (tool or cli):
        raise ConfigurationError("Externally callable routes require a name")
    if needs_approval and not (tool or cli):
        raise ConfigurationError("needs_approval requires tool=True or cli=True")


def normalize_inject(inject: ResourceMap | None) -> dict[str, Resource[Any]]:
    if inject is None:
        return {}
    normalized: dict[str, Resource[Any]] = {}
    for name, resource in inject.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise ConfigurationError(f"Invalid injected parameter name: {name!r}")
        if not isinstance(resource, Resource):
            raise TypeError("inject values must be Resource instances")
        normalized[name] = resource
    return normalized
