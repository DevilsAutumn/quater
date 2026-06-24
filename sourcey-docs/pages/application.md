---
description: Reference for Quater, RouteGroup, AppConfig, CORSConfig, and __version__, the application objects and their configuration options.
---

# Application Reference

This page documents `Quater`, `RouteGroup`, `AppConfig`, `CORSConfig`, and
`__version__`.

## Prerequisites

Read [Public API](/en/dev/api) for the route model and
[Deployment](/en/dev/deployment) for production settings.

```python
from quater import AppConfig, CORSConfig, Quater, RouteGroup, __version__
```

## Quater {#symbol-quater}

Added in `0.1.0a1`.

Application object that owns routes, config, middleware, lifespan hooks, state,
and adapters.

```python
Quater(
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
    mcp_docs_path: str | None = "/mcp/docs",
    mcp_allowed_origins: Iterable[str] | None = None,
    auth: Iterable[AuthConfig] | None = None,
    mcp_audit: AuditHook | None = None,
    action_approval: ActionApproval | None = None,
    access_logger: AccessLogHook | None = None,
    docs_path: str | None = "/docs",
    openapi_path: str | None = "/openapi.json",
    request_id_header: str | None = "x-request-id",
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str \| None` | `None` | App name used in generated metadata. |
| `config` | [`AppConfig`](#symbol-appconfig) \| None | `None` | Base immutable config. Keyword overrides win. |
| `debug` | `bool \| None` | `None` | Overrides `config.debug`. Debug responses include exception details. |
| `security` | `SecurityMode \| None` | `None` | Overrides `config.security`. Use `"strict"` for production. |
| `allowed_hosts` | `Iterable[str] \| None` | `None` | Overrides accepted Host headers. Empty strict mode accepts local hosts only. |
| `trusted_proxies` | `Iterable[str] \| None` | `None` | Proxy IPs or CIDR ranges trusted for forwarded headers. |
| `max_body_size` | `int \| str \| None` | `None` | Maximum body size. Strings accept `b`, `kb`, `mb`, or `gb`. |
| `max_form_parts` | `int \| None` | `None` | Maximum number of form fields and file parts. |
| `max_form_field_size` | `int \| str \| None` | `None` | Maximum size for one string form field. |
| `max_file_size` | `int \| str \| None` | `None` | Maximum size for one uploaded file. |
| `upload_spool_size` | `int \| str \| None` | `None` | Per-file size before upload data rolls to disk. |
| `max_tool_response_size` | `int \| str \| None` | `None` | Maximum MCP tool response body size. |
| `max_action_response_size` | `int \| str \| None` | `None` | Maximum CLI action response body size. |
| `cors` | [`CORSConfig`](#symbol-corsconfig) \| None | `None` | Browser CORS policy. |
| `content_security_policy` | `str \| None` | `None` | Adds `Content-Security-Policy` in strict and relaxed modes. |
| `mcp_docs_path` | `str \| None` | `"/mcp/docs"` | Human MCP docs path. `None` disables the page. |
| `mcp_allowed_origins` | `Iterable[str] \| None` | `None` | Browser origins allowed for MCP requests. |
| `auth` | `Iterable[`[`AuthConfig`](./auth#symbol-authconfig)`] \| None` | `None` | Per-surface authenticators. Exactly one runs per request, chosen by source. A surface with no covering `AuthConfig` is public; uncovered `mcp` and `cli` exposure is logged at startup with route names. A surface may be covered by at most one `AuthConfig`. |
| `mcp_audit` | `AuditHook \| None` | `None` | Receives redacted MCP tool-call audit events. |
| `action_approval` | [`ActionApproval`](./auth#symbol-actionapproval) \| None | `None` | Required when any tool/action uses `needs_approval=True`. |
| `access_logger` | [`AccessLogHook`](./observability#symbol-accessloghook) \| None | `None` | Receives structured access events. |
| `docs_path` | `str \| None` | `"/docs"` | Swagger UI path. `None` disables the page. |
| `openapi_path` | `str \| None` | `"/openapi.json"` | OpenAPI JSON path. `None` disables the document. |
| `request_id_header` | `str \| None` | `"x-request-id"` | Request id header to read and write. `None` disables the response header. |

Returns: `None`. Instantiate it and register routes on the object.

For list-like string settings such as `allowed_hosts`, `trusted_proxies`, and
`mcp_allowed_origins`, pass an iterable of strings. Quater rejects a single
plain string because Python would otherwise split it into characters.

Example:

```python
from quater import Quater

app = Quater(allowed_hosts=["api.example.com"])


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
```

### Route decorators

`get`, `post`, `put`, `patch`, and `delete` call `route()` with a fixed method.

```python
route(
    method: str,
    path: str,
    *,
    name: str | None = None,
    description: str | None = None,
    tool: bool = False,
    cli: bool = False,
    needs_approval: bool = False,
    public: bool | Iterable[str] = False,
    inject: ResourceMap | None = None,
    metadata: dict[str, Any] | None = None,
    before: Iterable[BeforeMiddleware] = (),
    after: Iterable[AfterMiddleware] = (),
    around: Iterable[AroundMiddleware] = (),
    exception_handlers: Iterable[ExceptionHandlerEntry] = (),
) -> Callable[[HandlerT], HandlerT]
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | `str` | required | HTTP method for `route()` and `add_route()`. |
| `path` | `str` | required | Route path such as `/orders/{order_id}`. |
| `name` | `str \| None` | `None` | Operation name. Defaults to the handler name. |
| `description` | `str \| None` | `None` | Human description for docs, MCP tools, and CLI actions. |
| `tool` | `bool` | `False` | Expose the route as an MCP tool. |
| `cli` | `bool` | `False` | Expose the route as a CLI action. |
| `needs_approval` | `bool` | `False` | Require approval before MCP or CLI execution. |
| `public` | `bool \| Iterable[str]` | `False` | Opt the route out of auth. `True` opens every surface it is exposed on; a list (`["api", "mcp", "cli"]`) opens only the named surfaces. |
| `inject` | `ResourceMap \| None` | `None` | Request resources injected into handler parameters. |
| `metadata` | `dict[str, Any] \| None` | `None` | Extra metadata for docs and extensions. |
| `before` | `Iterable[BeforeMiddleware]` | `()` | Middleware that can run before the handler. |
| `after` | `Iterable[AfterMiddleware]` | `()` | Middleware that can adjust the response. |
| `around` | `Iterable[AroundMiddleware]` | `()` | Middleware that wraps the pipeline. |
| `exception_handlers` | `Iterable[ExceptionHandlerEntry]` | `()` | Route-specific exception handlers. |

### Common methods and properties

| Member | Return | Description |
| --- | --- | --- |
| `routes` | `tuple[RouteDefinition, ...]` | Registered route definitions. Treat entries as read-only metadata. |
| `state` | [`State`](./request#symbol-state) | App-level attribute container. |
| `asgi` | `ASGIAdapter` | Explicit ASGI callable. |
| `rsgi` | `RSGIAdapter` | Explicit RSGI callable. |
| `wsgi` | `WSGIAdapter` | Explicit WSGI callable. |
| `include(group)` | [`RouteGroup`](#symbol-routegroup) | Include a top-level group. |
| `add_route(...)` | `RouteDefinition` | Register a route without decorator syntax. |
| `before_request(fn, *, surfaces=None)` | `fn` | Register global before middleware. Use `surfaces=["api"]`, `["mcp"]`, or `["cli"]` to limit where it runs. |
| `after_response(fn, *, surfaces=None)` | `fn` | Register global after middleware. Supports the same surface filter. |
| `around_request(fn, *, surfaces=None)` | `fn` | Register global around middleware. Supports the same surface filter. |
| `exception_handler(exc_type, *, surfaces=None)` | decorator | Register a global exception handler. Supports the same surface filter. |
| `on_startup(fn)` | `fn` | Register startup hook. |
| `on_shutdown(fn)` | `fn` | Register shutdown hook. |
| `startup()` | `None` | Compile routes and run startup hooks. |
| `shutdown()` | `None` | Run shutdown hooks. |
| `handle(request)` | [`Response`](./responses#symbol-response) | Handle an in-process request. |
| `validate_production()` | `None` | Compile routes and run production safety checks. |

Raises:

- `ImproperlyConfigured` for invalid config, a surface covered by more than one
  `AuthConfig`, missing `action_approval`, docs path conflicts, or reserved paths. An
  exposed `mcp` or `cli` surface with no covering `AuthConfig` is logged at
  startup, not raised.
- `MiddlewareStateError` when you register middleware after routes compile.
- `TypeError` when `include()` receives a non-`RouteGroup`.

## RouteGroup {#symbol-routegroup}

Added in `0.1.0a1`.

Compile-time group for related routes. Quater flattens groups when you include
them.

```python
RouteGroup(
    prefix: str = "",
    *,
    tags: Iterable[str] = (),
    inject: ResourceMap | None = None,
    metadata: Mapping[str, Any] | None = None,
    before: Iterable[BeforeMiddleware] = (),
    after: Iterable[AfterMiddleware] = (),
    around: Iterable[AroundMiddleware] = (),
    exception_handlers: Iterable[ExceptionHandlerEntry] = (),
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `prefix` | `str` | `""` | Prefix applied to child routes. Must start with `/` when set. |
| `tags` | `Iterable[str]` | `()` | OpenAPI tags inherited by child routes. |
| `inject` | `ResourceMap \| None` | `None` | Resources inherited by child routes. |
| `metadata` | `Mapping[str, Any] \| None` | `None` | Metadata inherited by child routes. |
| `before` | `Iterable[BeforeMiddleware]` | `()` | Before middleware inherited by routes. |
| `after` | `Iterable[AfterMiddleware]` | `()` | After middleware inherited by routes. |
| `around` | `Iterable[AroundMiddleware]` | `()` | Around middleware inherited by routes. |
| `exception_handlers` | `Iterable[ExceptionHandlerEntry]` | `()` | Exception handlers inherited by routes. |

Example:

```python
from quater import Quater, RouteGroup

app = Quater()
orders = RouteGroup(prefix="/orders", tags=["orders"])


@orders.get("/{order_id}")
async def get_order(order_id: str) -> dict[str, str]:
    return {"order_id": order_id}


app.include(orders)
```

Raises:

- `ImproperlyConfigured` when prefixes or paths are invalid.
- `ImproperlyConfigured` when a group includes itself, is included twice, or is
  modified after inclusion.
- `TypeError` when `include()` receives a non-`RouteGroup`.

## AppConfig {#symbol-appconfig}

Added in `0.1.0a1`.

Immutable application configuration. Most apps pass keywords to `Quater()`.

```python
AppConfig(
    debug: bool = False,
    security: SecurityMode = "strict",
    allowed_hosts: tuple[str, ...] = (),
    trusted_proxies: tuple[str, ...] = (),
    max_body_size: int = 2097152,
    max_form_parts: int = 1000,
    max_form_field_size: int = 1048576,
    max_file_size: int = 2097152,
    upload_spool_size: int = 1048576,
    max_tool_response_size: int = 1048576,
    max_action_response_size: int = 1048576,
    cors: CORSConfig | None = None,
    content_security_policy: str | None = None,
    docs_path: str | None = "/docs",
    openapi_path: str | None = "/openapi.json",
    mcp_docs_path: str | None = "/mcp/docs",
    mcp_allowed_origins: tuple[str, ...] = (),
    request_id_header: str | None = "x-request-id",
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `debug` | `bool` | `False` | Enables detailed framework error responses. |
| `security` | `SecurityMode` | `"strict"` | Security header mode. |
| `allowed_hosts` | `tuple[str, ...]` | `()` | Accepted Host headers. |
| `trusted_proxies` | `tuple[str, ...]` | `()` | Trusted proxy IPs and CIDR networks. |
| `max_body_size` | `int` | `2097152` | Maximum request body size in bytes. |
| `max_form_parts` | `int` | `1000` | Maximum number of form fields and file parts. |
| `max_form_field_size` | `int` | `1048576` | Maximum size for one string form field. |
| `max_file_size` | `int` | `2097152` | Maximum size for one uploaded file. |
| `upload_spool_size` | `int` | `1048576` | Per-file size before upload data rolls to disk. |
| `max_tool_response_size` | `int` | `1048576` | Maximum MCP tool response body size. |
| `max_action_response_size` | `int` | `1048576` | Maximum CLI action response body size. |
| `cors` | [`CORSConfig`](#symbol-corsconfig) \| None | `None` | Browser CORS policy. |
| `content_security_policy` | `str \| None` | `None` | CSP header value. |
| `docs_path` | `str \| None` | `"/docs"` | Swagger UI path. |
| `openapi_path` | `str \| None` | `"/openapi.json"` | OpenAPI JSON path. |
| `mcp_docs_path` | `str \| None` | `"/mcp/docs"` | Human MCP docs path. |
| `mcp_allowed_origins` | `tuple[str, ...]` | `()` | Browser origins allowed for MCP. |
| `request_id_header` | `str \| None` | `"x-request-id"` | Request id header. |

Quater reads limit defaults from `QUATER_*` environment variables when you use
`Quater()` without an explicit `config`. Constructor keyword options override
environment values.

List-like string fields are normalized to tuples and reject single plain
strings. Raises `ImproperlyConfigured` for unsupported security modes, invalid
paths, invalid header names, invalid size settings, invalid trusted proxies,
empty CSP, or `docs_path` without `openapi_path`.

## CORSConfig {#symbol-corsconfig}

Added in `0.1.0a1`.

Browser CORS policy. CORS is not authentication.

```python
CORSConfig(
    allowed_origins: tuple[str, ...],
    allowed_methods: tuple[str, ...] = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"),
    allowed_headers: tuple[str, ...] = (),
    expose_headers: tuple[str, ...] = (),
    allow_credentials: bool = False,
    max_age: int | None = None,
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `allowed_origins` | `tuple[str, ...]` | required | Browser origins allowed to read responses. |
| `allowed_methods` | `tuple[str, ...]` | common API methods | Valid HTTP method tokens advertised during preflight. |
| `allowed_headers` | `tuple[str, ...]` | `()` | Allowed request headers. Empty reflects sanitized requested headers. |
| `expose_headers` | `tuple[str, ...]` | `()` | Response headers browser code may read. |
| `allow_credentials` | `bool` | `False` | Whether browsers may send credentials. |
| `max_age` | `int \| None` | `None` | Browser preflight cache seconds. |

`allowed_methods` accepts standard methods and valid extension method tokens
such as `PROPFIND`. If you expose a custom method with `route("PROPFIND", ...)`
and browser clients call it cross-origin, add that method here too.

Raises `ImproperlyConfigured` for empty values, invalid method tokens, invalid
header names, wildcard origins with credentials, or negative `max_age`.

## __version__ {#symbol-version}

Added in `0.1.0a1`.

Installed Quater version.

```python
from quater import __version__

print(__version__)
```

Expected output:

```text
0.2.0
```

## What Can Go Wrong

`docs_path requires openapi_path`
: Disable both, or keep both enabled.

`RouteGroup prefix must start with '/'`
: Use `RouteGroup(prefix="/api")`.

`CORS wildcard origins cannot be used with credentials`
: Use explicit origins when `allow_credentials=True`.

`Production safety check failed:`
: Fix the listed production settings before serving traffic.

## Also See

- [Public API](/en/dev/api): usage examples for these objects.
- [Security](/en/dev/security): host, CORS, and production defaults.
- [Deployment](/en/dev/deployment): server options and production checks.
