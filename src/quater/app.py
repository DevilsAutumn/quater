"""Application root for Quater."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from quater._finalize import (
    add_request_finalizer,
    move_request_finalizers_to_response,
    move_response_finalizers,
    run_response_finalizers,
)
from quater._route_definition import (
    build_route_definition,
    validate_external_route_options,
)
from quater._state import State
from quater.actions.approval import ApprovalDeniedError, ApprovalRequiredError
from quater.actions.executor import execute_action, preflight_action
from quater.auth import AuthConfig, build_auth_map, run_authenticator, validate_auth
from quater.config import (
    _UNSET,
    AppConfig,
    MaxBodySize,
    SecurityMode,
    _Unset,
    docs_asset_paths,
)
from quater.core import (
    _SKIP_GLOBAL_MIDDLEWARE_METADATA,
    Handler,
    PublicSurfaces,
    RouteDefinition,
    exposed_surfaces,
)
from quater.cors import CORSConfig, add_cors_headers, is_cors_preflight
from quater.datastructures import normalize_response_headers
from quater.dependencies import ResourceMap
from quater.deployment import validate_production_config
from quater.exceptions import (
    BadRequestError,
    ConfigurationError,
    HTTPError,
    MiddlewareStateError,
    RequestJSONError,
)
from quater.lifespan import LifespanManager
from quater.middleware import (
    AfterMiddleware,
    AroundMiddleware,
    BeforeMiddleware,
    ExceptionHandlerEntry,
    ExceptionMiddleware,
    MiddlewareStack,
    after_middleware_for_surfaces,
    around_middleware_for_surfaces,
    before_middleware_for_surfaces,
    default_exception_response,
    exception_handler_for_surfaces,
    normalize_middleware_surfaces,
)
from quater.observability import (
    AccessLogHook,
    access_log_event,
    add_request_id_header,
    ensure_request_id,
)
from quater.protocol.actions import (
    ACTIONS_MANIFEST_PATH,
    ACTIONS_RPC_PATH,
    ActionResponseTooLargeError,
    action_manifest,
    preflight_payload,
    response_payload,
)
from quater.request import Request
from quater.response import (
    EmptyResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    validate_response,
)
from quater.router import Match, Router
from quater.security import (
    RequestSecurityContext,
    add_security_headers,
    prepare_request_security,
)
from quater.typing import ActionApproval, LifespanHook, RequestSource

logger = logging.getLogger("quater")

HandlerT = TypeVar("HandlerT", bound=Handler)
MCP_PATH = "/mcp"
ACTION_APPROVAL_REQUIRED_MESSAGE = "Approval-required actions require action_approval"
# Builtin routes served over HTTP but gated by an agent surface's AuthConfig.
_AUTH_SURFACE_METADATA = "quater_auth_surface"


_RESERVED_USER_ROUTE_PREFIXES = (MCP_PATH, "/__quater__")
_RESERVED_USER_ROUTE_PATHS = frozenset(
    {
        MCP_PATH,
        ACTIONS_MANIFEST_PATH,
        ACTIONS_RPC_PATH,
    }
)


if TYPE_CHECKING:
    from quater.actions.registry import ActionRegistry
    from quater.adapters.asgi import ASGIAdapter, ASGIReceive, ASGIScope, ASGISend
    from quater.adapters.rsgi import (
        RSGIAdapter,
        RSGICallbackResult,
        RSGIHTTPProtocol,
        RSGIScope,
        RSGIWebSocketProtocol,
    )
    from quater.adapters.wsgi import StartResponse, WSGIAdapter, WSGIEnvironment
    from quater.groups import RouteGroup
    from quater.tools.audit import AuditHook
    from quater.tools.registry import ToolRegistry


class Quater:
    """Application object that owns routes, configuration, and adapters.

    Create one instance per app. Register normal HTTP routes with decorators,
    and opt selected routes into MCP tools or Quater CLI actions with
    ``tool=True`` and ``cli=True``.
    """

    __slots__ = (
        "action_approval",
        "access_logger",
        "config",
        "mcp_audit",
        "name",
        "state",
        "_action_registry",
        "_auth_by_surface",
        "_asgi_adapter",
        "_lifespan",
        "_middleware",
        "_openapi_schema",
        "_rsgi_adapter",
        "_router",
        "_routes",
        "_routes_dirty",
        "_tool_registry",
        "_wsgi_adapter",
        "_wsgi_lifespan_warned",
    )

    def __init__(
        self,
        *,
        name: str | None = None,
        config: AppConfig | None = None,
        debug: bool | None = None,
        security: SecurityMode | None = None,
        allowed_hosts: Iterable[str] | None = None,
        trusted_proxies: Iterable[str] | None = None,
        max_body_size: MaxBodySize | None = None,
        max_form_parts: int | None = None,
        max_form_field_size: MaxBodySize | None = None,
        max_file_size: MaxBodySize | None = None,
        upload_spool_size: MaxBodySize | None = None,
        max_tool_response_size: MaxBodySize | None = None,
        max_action_response_size: MaxBodySize | None = None,
        cors: CORSConfig | None = None,
        content_security_policy: str | None = None,
        mcp_docs_path: str | None | _Unset = _UNSET,
        mcp_allowed_origins: Iterable[str] | None = None,
        auth: Iterable[AuthConfig] | None = None,
        mcp_audit: AuditHook | None = None,
        action_approval: ActionApproval | None = None,
        access_logger: AccessLogHook | None = None,
        docs_path: str | None | _Unset = _UNSET,
        openapi_path: str | None | _Unset = _UNSET,
        request_id_header: str | None | _Unset = _UNSET,
    ) -> None:
        self.name = name
        self.config = (config or AppConfig.from_environment())._with_overrides(
            debug=debug,
            security=security,
            allowed_hosts=allowed_hosts,
            trusted_proxies=trusted_proxies,
            max_body_size=max_body_size,
            max_form_parts=max_form_parts,
            max_form_field_size=max_form_field_size,
            max_file_size=max_file_size,
            upload_spool_size=upload_spool_size,
            max_tool_response_size=max_tool_response_size,
            max_action_response_size=max_action_response_size,
            cors=cors,
            content_security_policy=content_security_policy,
            docs_path=docs_path,
            openapi_path=openapi_path,
            mcp_docs_path=mcp_docs_path,
            mcp_allowed_origins=mcp_allowed_origins,
            request_id_header=request_id_header,
        )
        self.action_approval = action_approval
        self.access_logger = access_logger
        self.mcp_audit = mcp_audit
        self.state = State()
        self._auth_by_surface: dict[RequestSource, AuthConfig] = build_auth_map(auth)
        self._action_registry: ActionRegistry | None = None
        self._asgi_adapter: ASGIAdapter | None = None
        self._lifespan = LifespanManager()
        self._middleware = MiddlewareStack()
        self._openapi_schema: dict[str, object] | None = None
        self._rsgi_adapter: RSGIAdapter | None = None
        self._routes: list[RouteDefinition] = []
        self._router: Router | None = None
        self._tool_registry: ToolRegistry | None = None
        self._wsgi_adapter: WSGIAdapter | None = None
        self._wsgi_lifespan_warned = False
        self._routes_dirty = True

    @property
    def routes(self) -> tuple[RouteDefinition, ...]:
        """Registered route definitions."""

        return tuple(self._routes)

    @property
    def asgi(self) -> ASGIAdapter:
        adapter = self._asgi_adapter
        if adapter is None:
            from quater.adapters.asgi import ASGIAdapter

            adapter = ASGIAdapter(self)
            self._asgi_adapter = adapter
        return adapter

    @property
    def rsgi(self) -> RSGIAdapter:
        adapter = self._rsgi_adapter
        if adapter is None:
            from quater.adapters.rsgi import RSGIAdapter

            adapter = RSGIAdapter(self)
            self._rsgi_adapter = adapter
        return adapter

    @property
    def wsgi(self) -> WSGIAdapter:
        adapter = self._wsgi_adapter
        if adapter is None:
            from quater.adapters.wsgi import WSGIAdapter

            adapter = WSGIAdapter(self)
            self._wsgi_adapter = adapter
        return adapter

    def _warn_if_wsgi_skips_lifespan(self) -> None:
        # Checked on the first WSGI request (not at adapter construction): hooks
        # may be registered after `app.wsgi` is captured, e.g. a module-level
        # `application = app.wsgi` above the `@app.on_startup` decorators.
        if self._wsgi_lifespan_warned or not self._lifespan.has_hooks:
            return
        self._wsgi_lifespan_warned = True
        logger.warning(
            "WSGI is a compatibility-only interface and does not run lifespan "
            "hooks; on_startup/on_shutdown will not execute. Serve via RSGI or "
            "ASGI for lifespan support."
        )

    @property
    def __rsgi__(self) -> RSGIAdapter:
        return self.rsgi

    def __rsgi_init__(self, runner: object, *args: object, **kwargs: object) -> None:
        _run_rsgi_lifespan_callback(runner, self.startup())

    def __rsgi_del__(self, runner: object, *args: object, **kwargs: object) -> None:
        _run_rsgi_lifespan_callback(runner, self.shutdown())

    @overload
    def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
        /,
    ) -> Awaitable[None]: ...

    @overload
    def __call__(
        self,
        environ: WSGIEnvironment,
        start_response: StartResponse,
        /,
    ) -> Iterable[bytes]: ...

    @overload
    def __call__(
        self,
        scope: RSGIScope,
        protocol: RSGIHTTPProtocol | RSGIWebSocketProtocol,
        /,
    ) -> RSGICallbackResult: ...

    def __call__(
        self,
        scope_or_environ: object,
        receive_or_start_response_or_protocol: object,
        send: object | None = None,
        /,
    ) -> object:
        if send is not None:
            return self.asgi(
                cast("ASGIScope", scope_or_environ),
                cast("ASGIReceive", receive_or_start_response_or_protocol),
                cast("ASGISend", send),
            )

        if isinstance(scope_or_environ, dict):
            return self.wsgi(
                cast("WSGIEnvironment", scope_or_environ),
                cast("StartResponse", receive_or_start_response_or_protocol),
            )
        return self.rsgi(
            cast("RSGIScope", scope_or_environ),
            cast(
                "RSGIHTTPProtocol | RSGIWebSocketProtocol",
                receive_or_start_response_or_protocol,
            ),
        )

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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> RouteDefinition:
        """Register route metadata without compiling or matching it."""

        _validate_user_route_path(path)
        route = build_route_definition(
            method,
            path=path,
            handler=handler,
            name=name,
            description=description,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
            public=public,
            inject=inject,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )
        self._validate_action_approval_config(needs_approval=route.needs_approval)
        self._register_route_definition(route)
        return route

    def include(self, group: RouteGroup) -> RouteGroup:
        """Include a route group in the application."""

        from quater.groups import RouteGroup

        if not isinstance(group, RouteGroup):
            raise TypeError("include() requires a RouteGroup")
        group._ensure_app_includable()
        routes = group._flatten_routes()
        for route in routes:
            self._validate_route_definition(route)
        for route in routes:
            self._register_route_definition(route)
        group._mark_mounted()
        return group

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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> Callable[[HandlerT], HandlerT]:
        """Register a handler for an HTTP method and path."""

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
                public=public,
                inject=inject,
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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
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
            public=public,
            inject=inject,
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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
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
            public=public,
            inject=inject,
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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
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
            public=public,
            inject=inject,
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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
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
            public=public,
            inject=inject,
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
        public: PublicSurfaces = False,
        inject: ResourceMap | None = None,
        metadata: dict[str, Any] | None = None,
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
            public=public,
            inject=inject,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def compile_routes(self) -> Router:
        """Compile route definitions into a dispatcher."""

        for route in self._routes:
            self._validate_route_definition(route)

        self._router = Router.compile(
            (*self._routes, *self._builtin_routes()),
            middleware=self._middleware,
            debug=self.config.debug,
        )
        from quater.tools.registry import build_tool_registry

        self._tool_registry = build_tool_registry(tuple(self._routes))
        from quater.actions.registry import build_action_registry

        self._action_registry = build_action_registry(tuple(self._routes))
        self._validate_action_registry_security(self._action_registry)
        self._validate_auth_coverage()
        self._routes_dirty = False
        return self._router

    @overload
    def before_request(
        self,
        middleware: BeforeMiddleware,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> BeforeMiddleware: ...

    @overload
    def before_request(
        self,
        middleware: None = None,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> Callable[[BeforeMiddleware], BeforeMiddleware]: ...

    def before_request(
        self,
        middleware: BeforeMiddleware | None = None,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> BeforeMiddleware | Callable[[BeforeMiddleware], BeforeMiddleware]:
        """Register a global before-request middleware."""

        self._ensure_middleware_mutable()
        scoped_surfaces = normalize_middleware_surfaces(surfaces)

        def register(actual: BeforeMiddleware) -> BeforeMiddleware:
            self._ensure_middleware_mutable()
            self._middleware = MiddlewareStack(
                before=(
                    *self._middleware.before,
                    before_middleware_for_surfaces(actual, scoped_surfaces),
                ),
                after=self._middleware.after,
                around=self._middleware.around,
                exception_handlers=self._middleware.exception_handlers,
            )
            return actual

        if middleware is None:
            return register
        return register(middleware)

    @overload
    def after_response(
        self,
        middleware: AfterMiddleware,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> AfterMiddleware: ...

    @overload
    def after_response(
        self,
        middleware: None = None,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> Callable[[AfterMiddleware], AfterMiddleware]: ...

    def after_response(
        self,
        middleware: AfterMiddleware | None = None,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> AfterMiddleware | Callable[[AfterMiddleware], AfterMiddleware]:
        """Register a global after-response middleware."""

        self._ensure_middleware_mutable()
        scoped_surfaces = normalize_middleware_surfaces(surfaces)

        def register(actual: AfterMiddleware) -> AfterMiddleware:
            self._ensure_middleware_mutable()
            self._middleware = MiddlewareStack(
                before=self._middleware.before,
                after=(
                    *self._middleware.after,
                    after_middleware_for_surfaces(actual, scoped_surfaces),
                ),
                around=self._middleware.around,
                exception_handlers=self._middleware.exception_handlers,
            )
            return actual

        if middleware is None:
            return register
        return register(middleware)

    @overload
    def around_request(
        self,
        middleware: AroundMiddleware,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> AroundMiddleware: ...

    @overload
    def around_request(
        self,
        middleware: None = None,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> Callable[[AroundMiddleware], AroundMiddleware]: ...

    def around_request(
        self,
        middleware: AroundMiddleware | None = None,
        *,
        surfaces: Iterable[str] | None = None,
    ) -> AroundMiddleware | Callable[[AroundMiddleware], AroundMiddleware]:
        """Register a global around-request middleware."""

        self._ensure_middleware_mutable()
        scoped_surfaces = normalize_middleware_surfaces(surfaces)

        def register(actual: AroundMiddleware) -> AroundMiddleware:
            self._ensure_middleware_mutable()
            self._middleware = MiddlewareStack(
                before=self._middleware.before,
                after=self._middleware.after,
                around=(
                    *self._middleware.around,
                    around_middleware_for_surfaces(actual, scoped_surfaces),
                ),
                exception_handlers=self._middleware.exception_handlers,
            )
            return actual

        if middleware is None:
            return register
        return register(middleware)

    def exception_handler(
        self,
        exception_type: type[Exception],
        *,
        surfaces: Iterable[str] | None = None,
    ) -> Callable[[ExceptionMiddleware], ExceptionMiddleware]:
        """Register a global exception handler."""

        self._ensure_middleware_mutable()
        scoped_surfaces = normalize_middleware_surfaces(surfaces)

        def decorator(handler: ExceptionMiddleware) -> ExceptionMiddleware:
            self._ensure_middleware_mutable()
            self._middleware = MiddlewareStack(
                before=self._middleware.before,
                after=self._middleware.after,
                around=self._middleware.around,
                exception_handlers=(
                    *self._middleware.exception_handlers,
                    ExceptionHandlerEntry(
                        exception_type,
                        exception_handler_for_surfaces(handler, scoped_surfaces),
                    ),
                ),
            )
            return handler

        return decorator

    def on_startup(self, hook: LifespanHook) -> LifespanHook:
        """Register an async startup hook and return it for decorator usage."""

        return self._lifespan.on_startup(hook)

    def on_shutdown(self, hook: LifespanHook) -> LifespanHook:
        """Register an async shutdown hook and return it for decorator usage."""

        return self._lifespan.on_shutdown(hook)

    async def startup(self) -> None:
        """Run startup hooks once."""

        self.compile_routes()
        await self._lifespan.startup()

    async def shutdown(self) -> None:
        """Run shutdown hooks once after startup."""

        await self._lifespan.shutdown()

    async def handle(self, request: Request) -> Response:
        """Handle a normalized request through the core dispatcher."""

        return await self._handle_request(request)

    def validate_production(self) -> None:
        """Compile routes and fail if production safety checks do not pass."""

        self.compile_routes()
        validate_production_config(self)

    async def _handle_request(self, request: Request) -> Response:
        started_at = time.perf_counter()
        request.app = self
        ensure_request_id(request, self.config)
        context = RequestSecurityContext(
            host=None,
            scheme=request.scheme.lower(),
            client=request.client,
        )
        is_mcp_request = request.path == MCP_PATH
        router: Router | None = None
        match: Match | None = None
        try:
            context = prepare_request_security(request, self.config)
            if self.config.cors is not None and is_cors_preflight(request):
                return await self._finalize_request(
                    EmptyResponse(),
                    request,
                    context,
                    started_at=started_at,
                )
            if is_mcp_request:
                from quater.tools.mcp import mcp_request_context, validate_mcp_origin

                validate_mcp_origin(request, self.config)
                request.context = await mcp_request_context(request)
                await self._authenticate_mcp(request)
            if not is_mcp_request:
                router = self._compiled_router()
                match = router.match(request.method, request.path)
                if match.route is not None:
                    self._prepare_matched_route_context(
                        match.route.definition,
                        request,
                    )
                    if request.path == ACTIONS_RPC_PATH:
                        await self._authenticate_actions_rpc(request)
                    else:
                        await self._authenticate_http(
                            match.route.definition,
                            request,
                        )
        except Exception as exc:
            # Authentication or routing may have opened resources before failing;
            # tear them down in reverse order.
            await request._aexit_resources_for_error(exc)
            response = default_exception_response(exc, debug=self.config.debug)
            return await self._finalize_request(
                response,
                request,
                context,
                started_at=started_at,
            )

        if is_mcp_request:
            from quater.tools.mcp import handle_mcp_request

            response = await handle_mcp_request(
                request,
                self._compiled_tool_registry(),
                approval_hook=self.action_approval,
                audit_hook=self.mcp_audit,
                global_stack=self._middleware,
                debug=self.config.debug,
                max_response_size=self.config.max_tool_response_size,
            )
        else:
            if router is None or match is None:
                response = default_exception_response(
                    RuntimeError("Route dispatch state missing"),
                    debug=self.config.debug,
                )
            else:
                response = await router.dispatch_match(request, match)
        return await self._finalize_request(
            response,
            request,
            context,
            started_at=started_at,
        )

    def _compiled_router(self) -> Router:
        if self._router is None or self._routes_dirty:
            return self.compile_routes()
        return self._router

    def _compiled_tool_registry(self) -> ToolRegistry:
        if self._routes_dirty:
            self.compile_routes()
        if self._tool_registry is None or self._routes_dirty:
            from quater.tools.registry import build_tool_registry

            self._tool_registry = build_tool_registry(tuple(self._routes))
        return self._tool_registry

    def _compiled_action_registry(self) -> ActionRegistry:
        if self._routes_dirty:
            self.compile_routes()
        if self._action_registry is None or self._routes_dirty:
            from quater.actions.registry import build_action_registry

            self._action_registry = build_action_registry(tuple(self._routes))
            self._validate_action_registry_security(self._action_registry)
        return self._action_registry

    def _builtin_routes(self) -> tuple[RouteDefinition, ...]:
        routes: list[RouteDefinition] = []
        if self.config.openapi_path is not None:
            routes.append(
                RouteDefinition(
                    method="GET",
                    path=self.config.openapi_path,
                    handler=self._openapi_json,
                    name="quater_openapi_json",
                    metadata={"include_in_openapi": False},
                )
            )
        if self.config.docs_path is not None:
            from quater.docs.swagger import ensure_swagger_ui_assets_available

            ensure_swagger_ui_assets_available()
            routes.append(
                RouteDefinition(
                    method="GET",
                    path=self.config.docs_path,
                    handler=self._openapi_docs,
                    name="quater_openapi_docs",
                    metadata={"include_in_openapi": False},
                )
            )
            asset_paths = docs_asset_paths(self.config.docs_path)
            for asset_name, handler in self._swagger_ui_asset_handlers().items():
                routes.append(
                    RouteDefinition(
                        method="GET",
                        path=asset_paths[asset_name],
                        handler=handler,
                        name=f"quater_docs_{asset_name.replace('-', '_')}",
                        metadata={"include_in_openapi": False},
                    )
                )
        if self.config.mcp_docs_path is not None:
            routes.append(
                RouteDefinition(
                    method="GET",
                    path=self.config.mcp_docs_path,
                    handler=self._mcp_docs,
                    name="quater_mcp_docs",
                    metadata={
                        "include_in_openapi": False,
                        _AUTH_SURFACE_METADATA: "mcp",
                    },
                )
            )
        if self._has_cli_routes():
            routes.append(
                RouteDefinition(
                    method="GET",
                    path=ACTIONS_MANIFEST_PATH,
                    handler=self._actions_manifest,
                    name="quater_actions_manifest",
                    metadata={
                        "include_in_openapi": False,
                        "quater_builtin": "actions_manifest",
                        _AUTH_SURFACE_METADATA: "cli",
                    },
                )
            )
            routes.append(
                RouteDefinition(
                    method="POST",
                    path=ACTIONS_RPC_PATH,
                    handler=self._actions_call,
                    name="quater_actions_call",
                    metadata={
                        "include_in_openapi": False,
                        "quater_builtin": "actions_call",
                        _AUTH_SURFACE_METADATA: "cli",
                        _SKIP_GLOBAL_MIDDLEWARE_METADATA: True,
                    },
                )
            )
        return tuple(routes)

    def _has_cli_routes(self) -> bool:
        return any(route.cli for route in self._routes)

    async def _openapi_json(self) -> JSONResponse:
        return JSONResponse(self._openapi_schema_document())

    async def _openapi_docs(self) -> HTMLResponse:
        from quater.docs.html import DOCS_CSP, render_openapi_docs

        openapi_path = self.config.openapi_path
        if openapi_path is None:
            raise RuntimeError("OpenAPI docs require an OpenAPI path")

        return HTMLResponse(
            render_openapi_docs(
                openapi_json_path=openapi_path,
                swagger_ui_base_path=self.config.docs_path or "",
            ),
            headers={"content-security-policy": DOCS_CSP},
        )

    async def _swagger_ui_css(self) -> Response:
        from quater.docs.swagger import swagger_ui_asset_response

        return swagger_ui_asset_response("swagger-ui.css")

    async def _swagger_ui_bundle_js(self) -> Response:
        from quater.docs.swagger import swagger_ui_asset_response

        return swagger_ui_asset_response("swagger-ui-bundle.js")

    async def _swagger_ui_standalone_preset_js(self) -> Response:
        from quater.docs.swagger import swagger_ui_asset_response

        return swagger_ui_asset_response("swagger-ui-standalone-preset.js")

    async def _swagger_ui_initializer_js(self) -> Response:
        from quater.docs.swagger import swagger_ui_initializer_response

        openapi_path = self.config.openapi_path
        if openapi_path is None:
            raise RuntimeError("Swagger UI initializer requires an OpenAPI path")
        return swagger_ui_initializer_response(openapi_path)

    async def _swagger_ui_favicon(self) -> Response:
        from quater.docs.swagger import swagger_ui_asset_response

        return swagger_ui_asset_response("favicon-32x32.png")

    def _swagger_ui_asset_handlers(self) -> dict[str, Handler]:
        return {
            "swagger-ui.css": self._swagger_ui_css,
            "swagger-ui-bundle.js": self._swagger_ui_bundle_js,
            "swagger-ui-standalone-preset.js": self._swagger_ui_standalone_preset_js,
            "swagger-initializer.js": self._swagger_ui_initializer_js,
            "favicon-32x32.png": self._swagger_ui_favicon,
        }

    async def _mcp_docs(self) -> HTMLResponse:
        from quater.docs.html import DOCS_CSP, render_mcp_docs

        return HTMLResponse(
            render_mcp_docs(
                self._compiled_tool_registry(),
                mcp_endpoint=MCP_PATH,
                mcp_protected="mcp" in self._auth_by_surface,
            ),
            headers={"content-security-policy": DOCS_CSP},
        )

    async def _actions_manifest(self) -> JSONResponse:
        from quater import __version__

        return JSONResponse(
            action_manifest(
                self._compiled_action_registry(),
                service_name=self.name or "Quater",
                service_version=__version__,
            )
        )

    async def _actions_call(self, request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except RequestJSONError:
            return _action_error_response("invalid_json", "Malformed JSON body", 400)
        if not isinstance(payload, Mapping):
            return _action_error_response("invalid_request", "Invalid request", 400)

        action_name = payload.get("action")
        arguments = payload.get("arguments", {})
        dry_run = payload.get("dry_run", False)
        if not isinstance(action_name, str) or not action_name:
            return _action_error_response("invalid_action", "Invalid action", 400)
        request.context = replace(
            request.context,
            source="cli",
            entrypoint="server",
            tool_name=None,
            action_name=action_name,
        )
        if not isinstance(arguments, Mapping):
            return _action_error_response("invalid_arguments", "Invalid arguments", 400)
        if not isinstance(dry_run, bool):
            return _action_error_response("invalid_dry_run", "Invalid dry_run", 400)

        try:
            approval_token = _action_approval_token(payload)
        except BadRequestError as exc:
            return _action_error_response("invalid_approval", exc.detail, 400)

        action = self._compiled_action_registry().get(action_name)
        if action is None or not action.cli:
            return _action_error_response("unknown_action", "Unknown action", 404)

        try:
            if dry_run:
                result = await preflight_action(
                    action,
                    request,
                    cast(Mapping[str, object], arguments),
                    source="cli",
                    approval_token=approval_token,
                )
                return JSONResponse(preflight_payload(result))

            response = await execute_action(
                action,
                request,
                cast(Mapping[str, object], arguments),
                source="cli",
                global_stack=self._middleware,
                approval_hook=self.action_approval,
                approval_token=approval_token,
                debug=self.config.debug,
            )
        except ApprovalRequiredError as exc:
            return _action_error_response(
                "approval_required",
                "Approval required",
                409,
                action=exc.action,
                arguments_hash=exc.arguments_hash,
            )
        except ApprovalDeniedError as exc:
            return _action_error_response(
                "approval_denied",
                "Approval denied",
                403,
                action=exc.action,
                arguments_hash=exc.arguments_hash,
            )
        except BadRequestError as exc:
            return _action_error_response("bad_request", exc.detail, 400)
        except HTTPError as exc:
            return _action_error_response("http_error", exc.detail, exc.status_code)
        except Exception:
            return _action_error_response("action_failed", "Action call failed", 500)

        try:
            payload = await response_payload(
                response,
                max_response_size=self.config.max_action_response_size,
            )
        except ActionResponseTooLargeError:
            await run_response_finalizers(response)
            return _action_error_response(
                "response_too_large",
                "Response too large",
                502,
            )
        except Exception:
            await run_response_finalizers(response)
            return _action_error_response("action_failed", "Action call failed", 500)

        status_code = response.status_code if response.status_code >= 400 else 200
        return move_response_finalizers(
            response,
            JSONResponse(
                payload,
                status_code=status_code,
            ),
        )

    def _openapi_schema_document(self) -> dict[str, object]:
        if self._openapi_schema is None:
            from quater import __version__
            from quater.docs.openapi import build_openapi_schema

            self._openapi_schema = build_openapi_schema(
                tuple(self._routes),
                title=self.name or "Quater API",
                version=__version__,
                api_protected="api" in self._auth_by_surface,
            )
        return self._openapi_schema

    def _validate_route_exposure(
        self,
        route_name: str,
        *,
        tool: bool,
        cli: bool,
        needs_approval: bool,
    ) -> None:
        validate_external_route_options(
            route_name,
            tool=tool,
            cli=cli,
            needs_approval=needs_approval,
        )
        self._validate_action_approval_config(needs_approval=needs_approval)

    def _validate_action_approval_config(self, *, needs_approval: bool) -> None:
        if needs_approval and self.action_approval is None:
            raise ConfigurationError(ACTION_APPROVAL_REQUIRED_MESSAGE)

    def _validate_action_registry_security(
        self,
        registry: ActionRegistry,
    ) -> None:
        for action in registry.actions.values():
            self._validate_route_exposure(
                action.name,
                tool=action.tool,
                cli=action.cli,
                needs_approval=action.needs_approval,
            )

    def _validate_route_definition(self, route: RouteDefinition) -> None:
        _validate_user_route_path(route.path)
        self._validate_route_exposure(
            route.name,
            tool=route.tool,
            cli=route.cli,
            needs_approval=route.needs_approval,
        )

    def _register_route_definition(self, route: RouteDefinition) -> None:
        self._routes.append(route)
        self._action_registry = None
        self._openapi_schema = None
        self._tool_registry = None
        self._routes_dirty = True

    def _ensure_middleware_mutable(self) -> None:
        if self._router is not None:
            raise MiddlewareStateError(
                "Cannot register middleware after routes are compiled"
            )

    async def _authenticate_surface(
        self,
        surface: RequestSource,
        request: Request,
        *,
        public: tuple[RequestSource, ...],
    ) -> None:
        """Run the one authenticator that covers ``surface``, unless opted out.

        Skips when the route is public on this surface, or when no ``AuthConfig``
        covers it. An uncovered surface is intentionally public; agent surfaces
        are logged at startup so that exposure is visible.
        """

        if surface in public:
            return
        auth = self._auth_by_surface.get(surface)
        if auth is None:
            return
        await run_authenticator(auth, request)

    async def _authenticate_http(
        self,
        route: RouteDefinition,
        request: Request,
    ) -> None:
        surface = cast(
            RequestSource,
            route.metadata.get(_AUTH_SURFACE_METADATA, "api"),
        )
        await self._authenticate_surface(surface, request, public=route.public)

    async def _authenticate_mcp(self, request: Request) -> None:
        public: tuple[RequestSource, ...] = ()
        tool_name = request.context.tool_name
        if tool_name is not None:
            tool = self._compiled_tool_registry().get(tool_name)
            if tool is not None:
                public = tool.route.public
        await self._authenticate_surface("mcp", request, public=public)

    async def _authenticate_actions_rpc(self, request: Request) -> None:
        action_name = await _actions_rpc_action_name(request)
        request.context = replace(
            request.context,
            source="cli",
            entrypoint="server",
            tool_name=None,
            action_name=action_name,
        )
        public: tuple[RequestSource, ...] = ()
        if action_name is not None:
            action = self._compiled_action_registry().get(action_name)
            if action is not None and action.cli:
                public = action.route.public
        await self._authenticate_surface("cli", request, public=public)

    def _validate_auth_coverage(self) -> None:
        """Warn loudly when an exposed surface has no authenticator.

        Every surface behaves the same: if no ``AuthConfig`` covers it, its routes are
        public. That is allowed — the developer chooses what to protect and where.
        Uncovered agent surfaces are logged loudly because they are easy to expose
        accidentally.
        Routes a developer explicitly opens with ``public`` on an agent surface
        are also called out.
        """

        for auth in dict.fromkeys(self._auth_by_surface.values()):
            validate_auth(auth)

        protected_routes: dict[RequestSource, list[str]] = {
            "api": [],
            "mcp": [],
            "cli": [],
        }
        public_routes: dict[RequestSource, list[str]] = {
            "api": [],
            "mcp": [],
            "cli": [],
        }
        for route in self._routes:
            for surface in exposed_surfaces(tool=route.tool, cli=route.cli):
                if surface in route.public:
                    public_routes[surface].append(route.name)
                else:
                    protected_routes[surface].append(route.name)

        agent_surfaces: tuple[RequestSource, ...] = ("mcp", "cli")
        for surface in agent_surfaces:
            names = protected_routes[surface]
            if names and surface not in self._auth_by_surface:
                logger.warning(
                    "No AuthConfig covers the %r surface; "
                    "exposed routes are public: %s",
                    surface,
                    ", ".join(sorted(names)),
                )
        for surface in agent_surfaces:
            names = public_routes[surface]
            if names:
                logger.warning(
                    "Routes public on %r (callable without authentication): %s",
                    surface,
                    ", ".join(sorted(names)),
                )

    def _prepare_matched_route_context(
        self,
        route: RouteDefinition,
        request: Request,
    ) -> None:
        if route.metadata.get("quater_builtin") not in {
            "actions_manifest",
            "actions_call",
        }:
            return
        request.context = replace(
            request.context,
            source="cli",
            entrypoint="server",
            tool_name=None,
            action_name=None,
        )

    async def _finalize_request(
        self,
        response: Response,
        request: Request,
        context: RequestSecurityContext,
        *,
        started_at: float,
    ) -> Response:
        try:
            await request._aclose_function_resources()
        except Exception as exc:
            await request._aexit_resources_for_error(exc)
            error_response = default_exception_response(exc, debug=self.config.debug)
            response = move_response_finalizers(response, error_response)

        # Authentication may open request-scoped resources that the handler
        # never adopts (a request-only handler, discovery, or an early exit).
        # Defer their teardown onto the response so it is torn down once,
        # streaming-safe.
        if request._mark_request_resources_deferred():
            add_request_finalizer(request, request._aclose_request_resources)
        finalized = self._finalize_response(response, request, context)
        finalized = move_request_finalizers_to_response(request, finalized)
        if self.access_logger is not None:
            event = access_log_event(
                request,
                finalized,
                started_at=started_at,
            )
            with suppress(Exception):
                await self.access_logger(event)
        return finalized

    def _finalize_response(
        self,
        response: Response,
        request: Request,
        context: RequestSecurityContext,
    ) -> Response:
        try:
            if self.config.cors is not None:
                response = add_cors_headers(response, request, self.config.cors)
            response = add_security_headers(response, context, self.config)
            response = add_request_id_header(response, request, self.config)
            response.headers = normalize_response_headers(response.headers)
            validate_response(response)
            return response
        except (TypeError, ValueError) as exc:
            fallback = default_exception_response(exc, debug=self.config.debug)
            fallback = add_security_headers(fallback, context, self.config)
            fallback = add_request_id_header(fallback, request, self.config)
            fallback.headers = normalize_response_headers(fallback.headers)
            validate_response(fallback)
            return fallback


async def _actions_rpc_action_name(request: Request) -> str | None:
    """Read just the action name from a remote-CLI RPC body, before auth.

    The read is bounded by ``max_body_size`` (via ``request.json``) and never
    binds arguments. It brings the remote CLI to MCP parity: the authenticator
    sees ``request.context.action_name`` and can pick the matching policy.
    """

    try:
        payload = await request.json()
    except RequestJSONError:
        return None
    if not isinstance(payload, Mapping):
        return None
    name = payload.get("action")
    return name if isinstance(name, str) and name else None


def _action_approval_token(payload: Mapping[object, object]) -> str | None:
    value = payload.get("approval_token", payload.get("approvalToken"))
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError("Invalid approval token")
    return value


def _run_rsgi_lifespan_callback(
    runner: object,
    callback: Awaitable[None],
) -> None:
    run = getattr(runner, "_run", None)
    if callable(run):
        run(callback)
        return

    run_until_complete = getattr(runner, "run_until_complete", None)
    if callable(run_until_complete):
        run_until_complete(callback)
        return

    close = getattr(callback, "close", None)
    if callable(close):
        close()
    raise RuntimeError("RSGI lifespan runner is unavailable")


def _validate_user_route_path(path: str) -> None:
    normalized = _normalized_user_route_path(path)
    if normalized is None:
        return
    if normalized in _RESERVED_USER_ROUTE_PATHS or any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _RESERVED_USER_ROUTE_PREFIXES
    ):
        raise ConfigurationError(
            f"Route path {path!r} is reserved by Quater. "
            "Choose a different application route."
        )


def _normalized_user_route_path(path: str) -> str | None:
    if not path.startswith("/"):
        return None
    parts = [part for part in path.strip("/").split("/") if part]
    return "/" if not parts else "/" + "/".join(parts)


def _action_error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    action: str | None = None,
    arguments_hash: str | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if action is not None:
        error["action"] = action
    if arguments_hash is not None:
        error["arguments_hash"] = arguments_hash
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)
