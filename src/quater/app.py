"""Application root for Quater."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from quater.actions.approval import ApprovalDeniedError, ApprovalRequiredError
from quater.actions.descriptions import resolve_action_description
from quater.actions.executor import execute_action, preflight_action
from quater.auth import authenticate_request
from quater.config import (
    _UNSET,
    AppConfig,
    MaxBodySize,
    SecurityMode,
    _Unset,
    docs_asset_paths,
)
from quater.core import Handler, RouteDefinition
from quater.cors import CORSConfig, add_cors_headers, is_cors_preflight
from quater.datastructures import normalize_response_headers
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
    default_exception_response,
)
from quater.protocol.actions import (
    ACTIONS_MANIFEST_PATH,
    ACTIONS_RPC_PATH,
    action_manifest,
    preflight_payload,
    response_payload,
)
from quater.request import Request
from quater.response import EmptyResponse, HTMLResponse, JSONResponse, Response
from quater.router import Router
from quater.security import (
    RequestSecurityContext,
    add_security_headers,
    prepare_request_security,
    resolve_request_security_context,
)
from quater.tools.descriptions import (
    normalize_route_description,
    resolve_tool_description,
)
from quater.typing import ActionApproval, Authenticate, LifespanHook, RequestContext

HandlerT = TypeVar("HandlerT", bound=Handler)
MCP_PATH = "/mcp"
MCP_AUTH_REQUIRED_MESSAGE = "MCP tools require mcp_auth"
CLI_AUTH_REQUIRED_MESSAGE = "CLI actions require cli_auth"
ACTION_APPROVAL_REQUIRED_MESSAGE = "Approval-required actions require action_approval"


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
    from quater.tools.audit import AuditHook
    from quater.tools.registry import ToolRegistry


class Quater:
    """Central Quater application object."""

    __slots__ = (
        "action_approval",
        "cli_auth",
        "config",
        "mcp_audit",
        "mcp_auth",
        "name",
        "_action_registry",
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
        cors: CORSConfig | None = None,
        content_security_policy: str | None = None,
        mcp_docs_path: str | None | _Unset = _UNSET,
        mcp_allowed_origins: Iterable[str] | None = None,
        mcp_auth: Authenticate | None = None,
        mcp_audit: AuditHook | None = None,
        cli_auth: Authenticate | None = None,
        action_approval: ActionApproval | None = None,
        docs_path: str | None | _Unset = _UNSET,
        openapi_path: str | None | _Unset = _UNSET,
    ) -> None:
        self.name = name
        self.config = (config or AppConfig())._with_overrides(
            debug=debug,
            security=security,
            allowed_hosts=allowed_hosts,
            trusted_proxies=trusted_proxies,
            max_body_size=max_body_size,
            cors=cors,
            content_security_policy=content_security_policy,
            docs_path=docs_path,
            openapi_path=openapi_path,
            mcp_docs_path=mcp_docs_path,
            mcp_allowed_origins=mcp_allowed_origins,
        )
        self.action_approval = action_approval
        self.cli_auth = cli_auth
        self.mcp_audit = mcp_audit
        self.mcp_auth = mcp_auth
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

    @property
    def __rsgi__(self) -> RSGIAdapter:
        return self.rsgi

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
        auth: Authenticate | None = None,
        metadata: dict[str, Any] | None = None,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> RouteDefinition:
        """Register route metadata without compiling or matching it."""

        route_name = name
        if route_name is None:
            discovered_name = getattr(handler, "__name__", None)
            route_name = (
                discovered_name if isinstance(discovered_name, str) else "anonymous"
            )
        route_description = self._resolve_route_description(
            route_name,
            description,
            handler,
            tool=tool,
            cli=cli,
        )
        self._validate_route_exposure(
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
        self._action_registry = None
        self._openapi_schema = None
        self._tool_registry = None
        self._routes_dirty = True
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
            auth=auth,
            metadata=metadata,
            before=before,
            after=after,
            around=around,
            exception_handlers=exception_handlers,
        )

    def compile_routes(self) -> Router:
        """Compile route definitions into a dispatcher."""

        self._router = Router.compile(
            (*self._routes, *self._builtin_routes()),
            middleware=self._middleware,
            debug=self.config.debug,
        )
        from quater.tools.registry import build_tool_registry

        self._tool_registry = build_tool_registry(tuple(self._routes))
        if self._tool_registry.tools and self.mcp_auth is None:
            raise ConfigurationError(MCP_AUTH_REQUIRED_MESSAGE)
        from quater.actions.registry import build_action_registry

        self._action_registry = build_action_registry(tuple(self._routes))
        self._validate_action_registry_security(self._action_registry)
        self._routes_dirty = False
        return self._router

    def before_request(self, middleware: BeforeMiddleware) -> BeforeMiddleware:
        """Register a global before-request middleware."""

        self._ensure_middleware_mutable()
        self._middleware = MiddlewareStack(
            before=(*self._middleware.before, middleware),
            after=self._middleware.after,
            around=self._middleware.around,
            exception_handlers=self._middleware.exception_handlers,
        )
        return middleware

    def after_response(self, middleware: AfterMiddleware) -> AfterMiddleware:
        """Register a global after-response middleware."""

        self._ensure_middleware_mutable()
        self._middleware = MiddlewareStack(
            before=self._middleware.before,
            after=(*self._middleware.after, middleware),
            around=self._middleware.around,
            exception_handlers=self._middleware.exception_handlers,
        )
        return middleware

    def around_request(self, middleware: AroundMiddleware) -> AroundMiddleware:
        """Register a global around-request middleware."""

        self._ensure_middleware_mutable()
        self._middleware = MiddlewareStack(
            before=self._middleware.before,
            after=self._middleware.after,
            around=(*self._middleware.around, middleware),
            exception_handlers=self._middleware.exception_handlers,
        )
        return middleware

    def exception_handler(
        self,
        exception_type: type[Exception],
    ) -> Callable[[ExceptionMiddleware], ExceptionMiddleware]:
        """Register a global exception handler."""

        def decorator(handler: ExceptionMiddleware) -> ExceptionMiddleware:
            self._ensure_middleware_mutable()
            self._middleware = MiddlewareStack(
                before=self._middleware.before,
                after=self._middleware.after,
                around=self._middleware.around,
                exception_handlers=(
                    *self._middleware.exception_handlers,
                    ExceptionHandlerEntry(exception_type, handler),
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

        await self._lifespan.startup()

    async def shutdown(self) -> None:
        """Run shutdown hooks once after startup."""

        await self._lifespan.shutdown()

    async def handle(self, request: Request) -> Response:
        """Handle a normalized request through the core dispatcher."""

        return await self._handle_request(request)

    async def _handle_request(self, request: Request) -> Response:
        context = resolve_request_security_context(request, self.config)
        is_mcp_request = request.path == MCP_PATH
        try:
            context = prepare_request_security(request, self.config)
            if self.config.cors is not None and is_cors_preflight(request):
                return self._finalize_response(EmptyResponse(), request, context)
            if is_mcp_request:
                from quater.tools.mcp import mcp_request_context, validate_mcp_origin

                validate_mcp_origin(request, self.config)
                request.context = await mcp_request_context(request)
                if self.mcp_auth is not None:
                    await authenticate_request(self.mcp_auth, request)
            if not is_mcp_request:
                router = self._compiled_router()
                match = router.match(request.method, request.path)
                if match.route is not None:
                    self._prepare_matched_route_context(
                        match.route.definition,
                        request,
                    )
                    await self._authenticate_route(match.route.definition, request)
        except Exception as exc:
            response = default_exception_response(exc, debug=self.config.debug)
            return self._finalize_response(response, request, context)

        if is_mcp_request:
            from quater.tools.mcp import handle_mcp_request

            response = await handle_mcp_request(
                request,
                self._compiled_tool_registry(),
                transport_auth=self.mcp_auth,
                approval_hook=self.action_approval,
                audit_hook=self.mcp_audit,
                debug=self.config.debug,
            )
        else:
            response = await router.dispatch_match(request, match)
        return self._finalize_response(response, request, context)

    def _compiled_router(self) -> Router:
        if self._router is None or self._routes_dirty:
            return self.compile_routes()
        return self._router

    def _compiled_tool_registry(self) -> ToolRegistry:
        if self._tool_registry is None or self._routes_dirty:
            from quater.tools.registry import build_tool_registry

            self._tool_registry = build_tool_registry(tuple(self._routes))
            if self._tool_registry.tools and self.mcp_auth is None:
                raise ConfigurationError(MCP_AUTH_REQUIRED_MESSAGE)
        return self._tool_registry

    def _compiled_action_registry(self) -> ActionRegistry:
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
                    auth=self.mcp_auth,
                    metadata={"include_in_openapi": False},
                )
            )
        if self._has_cli_routes():
            routes.append(
                RouteDefinition(
                    method="GET",
                    path=ACTIONS_MANIFEST_PATH,
                    handler=self._actions_manifest,
                    name="quater_actions_manifest",
                    auth=self.cli_auth,
                    metadata={
                        "include_in_openapi": False,
                        "quater_builtin": "actions_manifest",
                    },
                )
            )
            routes.append(
                RouteDefinition(
                    method="POST",
                    path=ACTIONS_RPC_PATH,
                    handler=self._actions_call,
                    name="quater_actions_call",
                    auth=self.cli_auth,
                    metadata={
                        "include_in_openapi": False,
                        "quater_builtin": "actions_call",
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
                    source="remote_cli",
                    authenticated_by=self.cli_auth,
                    approval_token=approval_token,
                )
                return JSONResponse(preflight_payload(result))

            response = await execute_action(
                action,
                request,
                cast(Mapping[str, object], arguments),
                source="remote_cli",
                authenticated_by=self.cli_auth,
                approval_hook=self.action_approval,
                approval_token=approval_token,
            )
            payload = await response_payload(response)
            status_code = response.status_code if response.status_code >= 400 else 200
            return JSONResponse(
                payload,
                status_code=status_code,
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
        except ValueError:
            return _action_error_response(
                "response_too_large",
                "Response too large",
                502,
            )
        except Exception:
            return _action_error_response("action_failed", "Action call failed", 500)

    def _openapi_schema_document(self) -> dict[str, object]:
        if self._openapi_schema is None:
            from quater import __version__
            from quater.docs.openapi import build_openapi_schema

            self._openapi_schema = build_openapi_schema(
                tuple(self._routes),
                title=self.name or "Quater API",
                version=__version__,
            )
        return self._openapi_schema

    def _resolve_route_description(
        self,
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

    def _validate_route_exposure(
        self,
        route_name: str,
        *,
        tool: bool,
        cli: bool,
        needs_approval: bool,
    ) -> None:
        if route_name == "anonymous" and (tool or cli):
            raise ConfigurationError("Externally callable routes require a name")
        if tool and self.mcp_auth is None:
            raise ConfigurationError(MCP_AUTH_REQUIRED_MESSAGE)
        if cli and self.cli_auth is None:
            raise ConfigurationError(CLI_AUTH_REQUIRED_MESSAGE)
        if needs_approval and not (tool or cli):
            raise ConfigurationError("needs_approval requires tool=True or cli=True")
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

    def _ensure_middleware_mutable(self) -> None:
        if self._router is not None:
            raise MiddlewareStateError(
                "Cannot register middleware after routes are compiled"
            )

    async def _authenticate_route(
        self,
        route: RouteDefinition,
        request: Request,
    ) -> None:
        if route.auth is None or request.auth is not None:
            return
        await authenticate_request(route.auth, request)

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
        request.context = RequestContext(source="remote_cli")

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
            response.headers = normalize_response_headers(response.headers)
            return response
        except (TypeError, ValueError) as exc:
            fallback = default_exception_response(exc, debug=self.config.debug)
            fallback = add_security_headers(fallback, context, self.config)
            fallback.headers = normalize_response_headers(fallback.headers)
            return fallback


def _action_approval_token(payload: Mapping[object, object]) -> str | None:
    value = payload.get("approval_token", payload.get("approvalToken"))
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError("Invalid approval token")
    return value


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
