"""Route grouping primitives."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import replace
from typing import Any, TypeVar

from quater.actions.descriptions import resolve_action_description
from quater.core import Handler, RouteDefinition
from quater.exceptions import ConfigurationError
from quater.middleware import (
    AfterMiddleware,
    AroundMiddleware,
    BeforeMiddleware,
    ExceptionHandlerEntry,
    MiddlewareStack,
    merge_middleware_stack,
)
from quater.tools.descriptions import (
    normalize_route_description,
    resolve_tool_description,
)
from quater.typing import AuthContext, Authenticate, AuthRequest

HandlerT = TypeVar("HandlerT", bound=Handler)


class RouteGroup:
    """Compile-time group for routes that share prefix, metadata, and policy.

    Use groups to organize feature areas without adding another router to the
    request path. Quater flattens a group into normal route definitions when
    the group is included in the app.
    """

    __slots__ = (
        "auth",
        "metadata",
        "middleware",
        "prefix",
        "_groups",
        "_mounted",
        "_parented",
        "_routes",
    )

    def __init__(
        self,
        prefix: str = "",
        *,
        tags: Iterable[str] = (),
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> None:
        group_metadata = dict(metadata or {})
        group_tags = _merge_tags(
            _metadata_tags(group_metadata.get("tags")),
            _normalize_tags(tags),
        )
        if group_tags:
            group_metadata["tags"] = group_tags

        self.auth = auth
        self.metadata = group_metadata
        self.middleware = MiddlewareStack.from_parts(
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )
        self.prefix = _normalize_prefix(prefix)
        self._groups: list[RouteGroup] = []
        self._mounted = False
        self._parented = False
        self._routes: list[RouteDefinition] = []

    @property
    def routes(self) -> tuple[RouteDefinition, ...]:
        """Routes registered directly on this group."""

        return tuple(self._routes)

    @property
    def groups(self) -> tuple[RouteGroup, ...]:
        """Child groups registered directly on this group."""

        return tuple(self._groups)

    def include(self, group: RouteGroup) -> RouteGroup:
        """Include a child group beneath this group."""

        self._ensure_mutable()
        if not isinstance(group, RouteGroup):
            raise TypeError("include() requires a RouteGroup")
        if group is self or group._contains(self):
            raise ConfigurationError("Route groups cannot include themselves")
        if group._parented or group._mounted:
            raise ConfigurationError("Route groups can only be included once")
        group._parented = True
        self._groups.append(group)
        return group

    def add_route(
        self,
        method: str,
        path: str,
        handler: Handler,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> RouteDefinition:
        """Register route metadata on the group."""

        self._ensure_mutable()
        _validate_group_route_path(path)
        route_name = _route_name(handler, name)
        route_description = _resolve_route_description(
            route_name,
            description,
            handler,
            tool=tool,
            cli=cli,
        )
        _validate_external_route_options(
            route_name,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
        )

        route = RouteDefinition(
            method=method.upper(),
            path=path,
            handler=handler,
            name=route_name,
            description=route_description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            auth=auth,
            metadata=dict(metadata or {}),
            middleware=MiddlewareStack.from_parts(
                before=before,
                after=after,
                around=around,
                exception_handlers=exception_handlers,
            ),
        )
        self._routes.append(route)
        return route

    def route(
        self,
        method: str,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        """Register a handler for an HTTP method and group-relative path."""

        def decorator(handler: HandlerT) -> HandlerT:
            self.add_route(
                method,
                path,
                handler,
                name=name,
                description=description,
                tool=tool,
                cli=cli,
                needs_approval=needs_approval,
                auth=auth,
                metadata=metadata,
                before=before,
                after=after,
                around=around,
                exception_handlers=exception_handlers,
            )
            return handler

        return decorator

    def get(
        self,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        return self.route(
            "GET",
            path,
            name=name,
            description=description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            auth=auth,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def post(
        self,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        return self.route(
            "POST",
            path,
            name=name,
            description=description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            auth=auth,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def put(
        self,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        return self.route(
            "PUT",
            path,
            name=name,
            description=description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            auth=auth,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def patch(
        self,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        return self.route(
            "PATCH",
            path,
            name=name,
            description=description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            auth=auth,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def delete(
        self,
        path: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tool: bool = False,
        cli: bool = False,
        needs_approval: bool = False,
        auth: Authenticate | None = None,
        metadata: Mapping[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        return self.route(
            "DELETE",
            path,
            name=name,
            description=description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            auth=auth,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def _flatten_routes(self) -> tuple[RouteDefinition, ...]:
        return tuple(
            self._iter_flattened_routes(
                prefix="",
                metadata={},
                auth=None,
                middleware=MiddlewareStack(),
            )
        )

    def _iter_flattened_routes(
        self,
        *,
        prefix: str,
        metadata: Mapping[str, Any],
        auth: Authenticate | None,
        middleware: MiddlewareStack,
    ) -> Iterator[RouteDefinition]:
        group_prefix = _join_prefix(prefix, self.prefix)
        group_metadata = _merge_metadata(metadata, self.metadata)
        group_auth = _compose_auth(auth, self.auth)
        group_middleware = merge_middleware_stack(middleware, self.middleware)

        for route in self._routes:
            yield replace(
                route,
                path=_join_route_path(group_prefix, route.path),
                auth=_compose_auth(group_auth, route.auth),
                metadata=_merge_metadata(group_metadata, route.metadata),
                middleware=merge_middleware_stack(group_middleware, route.middleware),
            )

        for group in self._groups:
            yield from group._iter_flattened_routes(
                prefix=group_prefix,
                metadata=group_metadata,
                auth=group_auth,
                middleware=group_middleware,
            )

    def _contains(self, target: RouteGroup) -> bool:
        return any(group is target or group._contains(target) for group in self._groups)

    def _mark_mounted(self) -> None:
        self._mounted = True
        for group in self._groups:
            group._mark_mounted()

    def _ensure_app_includable(self) -> None:
        if self._parented:
            raise ConfigurationError("Only top-level route groups can be included")
        if self._mounted:
            raise ConfigurationError("Route group has already been included")

    def _ensure_mutable(self) -> None:
        if self._mounted:
            raise ConfigurationError(
                "Cannot modify a route group after it has been included"
            )


def _route_name(handler: Handler, explicit_name: str | None) -> str:
    if explicit_name is not None:
        return explicit_name
    discovered_name = getattr(handler, "__name__", None)
    return discovered_name if isinstance(discovered_name, str) else "anonymous"


def _resolve_route_description(
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


def _validate_external_route_options(
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


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    if not prefix.startswith("/"):
        raise ConfigurationError("RouteGroup prefix must start with '/'")
    if "?" in prefix or "#" in prefix:
        raise ConfigurationError(
            "RouteGroup prefix must not include query strings or fragments"
        )
    return _slash_path(prefix)


def _validate_group_route_path(path: str) -> None:
    if not path.startswith("/"):
        raise ConfigurationError("RouteGroup route paths must start with '/'")
    if "?" in path or "#" in path:
        raise ConfigurationError(
            "RouteGroup route paths must not include query strings or fragments"
        )


def _join_prefix(parent: str, child: str) -> str:
    if not parent:
        return child
    if not child:
        return parent
    return _slash_path(f"{parent}/{child.strip('/')}")


def _join_route_path(prefix: str, path: str) -> str:
    _validate_group_route_path(path)
    route_path = _slash_path(path)
    if not prefix:
        return route_path
    if route_path == "/":
        return prefix
    return _slash_path(f"{prefix}/{route_path.strip('/')}")


def _slash_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    return "/" if not parts else "/" + "/".join(parts)


def _merge_metadata(
    parent: Mapping[str, Any],
    child: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(parent)
    merged.update(child)
    tags = _merge_tags(
        _metadata_tags(parent.get("tags")),
        _metadata_tags(child.get("tags")),
    )
    if tags:
        merged["tags"] = tags
    return merged


def _metadata_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _normalize_tags(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, str | bytes):
        raise ConfigurationError("RouteGroup tags must be non-empty strings")
    tags = tuple(values)
    if any(not isinstance(tag, str) or not tag for tag in tags):
        raise ConfigurationError("RouteGroup tags must be non-empty strings")
    return tags


def _merge_tags(
    parent: Iterable[str],
    child: Iterable[str],
) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in (*tuple(parent), *tuple(child)):
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tuple(tags)


def _compose_auth(
    parent: Authenticate | None,
    child: Authenticate | None,
) -> Authenticate | None:
    if parent is None:
        return child
    if child is None:
        return parent

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        parent_context = await parent(ctx)
        if parent_context is None:
            return None
        child_context = await child(ctx)
        if child_context is None:
            return None
        return child_context

    return authenticate


__all__ = ["RouteGroup"]
