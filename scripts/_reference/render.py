"""Per-page markdown renderers and the top-level orchestration helper."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from _reference.manual import read_manual_reference
from _reference.pages import PAGES, ReferencePage, page_symbols
from _reference.paths import GENERATED_HEADER, REFERENCE_DIR
from _reference.signatures import (
    attribute_value,
    callable_signature,
    class_signature,
    code_block,
    method_signature,
    signature_block,
)
from _reference.tables import (
    CLI_CALL_OPTIONS,
    CLI_TEST_CLIENT_OPTIONS,
    DELETE_COOKIE_OPTIONS,
    GROUP_ROUTE_OPTIONS,
    HTTP_ERROR_OPTIONS,
    MCP_TEST_CLIENT_OPTIONS,
    MCP_TOOLS_CALL_OPTIONS,
    PARAMETER_DOCS,
    PARAMETER_OPTIONS,
    QUATER_OPTIONS,
    REQUEST_CONSTRUCTOR_OPTIONS,
    RESPONSE_DOCS,
    RESPONSE_OPTIONS,
    ROUTE_GROUP_OPTIONS,
    ROUTE_OPTIONS,
    SET_COOKIE_OPTIONS,
    SIGNED_COOKIE_SIGNER_OPTIONS,
    TEST_CLIENT_OPTIONS,
    TEST_CLIENT_REQUEST_OPTIONS,
    TEST_RESPONSE_OPTIONS,
    field_table,
    type_section,
    validated_function_option_table,
    validated_option_table,
)
from _reference.types import context_row, import_link, symbol_heading


def new_page(title: str) -> list[str]:
    return [GENERATED_HEADER, "", f"# {title}", ""]


def symbol_intro(
    lines: list[str],
    package: Any,
    symbol: str,
    summary: str,
    details: Sequence[str],
) -> None:
    lines.extend(
        [symbol_heading(symbol), "", source_line(package, symbol), "", summary, ""]
    )
    if details:
        lines.extend([*details, ""])


def source_line(package: Any, symbol: str) -> str:
    if symbol == "__version__":
        return "Public import: `from quater import __version__`."
    return f"Public import: `from quater import {symbol}`."


def finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


def render_reference(
    package: Any,
    public_api: tuple[str, ...],
    pages_by_symbol: Mapping[str, ReferencePage],
) -> dict[Path, str]:
    manual_outputs = read_manual_reference(public_api, pages_by_symbol)
    if manual_outputs is not None:
        return manual_outputs

    return {
        REFERENCE_DIR / "index.md": render_index(public_api, pages_by_symbol),
        REFERENCE_DIR / "application.md": render_application(package),
        REFERENCE_DIR / "resources.md": render_resources(package),
        REFERENCE_DIR / "request.md": render_request(package),
        REFERENCE_DIR / "parameters.md": render_parameters(package),
        REFERENCE_DIR / "responses.md": render_responses(package),
        REFERENCE_DIR / "auth.md": render_auth(package),
        REFERENCE_DIR / "observability.md": render_observability(package),
        REFERENCE_DIR / "testing.md": render_testing(package),
    }


def render_index(
    public_api: tuple[str, ...],
    pages_by_symbol: Mapping[str, ReferencePage],
) -> str:
    lines = new_page("Reference")
    lines.extend(
        [
            "These pages document the public objects you can import from `quater`.",
            "They are meant for quick lookup after you understand the concept.",
            "",
            "If you are still learning the framework, start with the",
            "[Quickstart](/en/dev/quickstart) and then come back here for",
            "exact names and signatures.",
            "",
            "For import guarantees, read [Stability](/en/dev/stability).",
            "",
            "## Pages",
            "",
            "| Page | Use it for |",
            "| --- | --- |",
        ]
    )
    for page in PAGES:
        lines.append(f"| [{page.title}](./{page.slug}) | {page.description} |")

    lines.extend(
        [
            "",
            "## Public Imports",
            "",
            "Use top-level imports for normal app code. These are the documented",
            "symbols Quater expects application code to use.",
            "",
        ]
    )
    for page in PAGES:
        names = [name for name in public_api if pages_by_symbol[name] == page]
        imports = ", ".join(import_link(name, page) for name in names)
        lines.append(f"- **{page.title}:** {imports}")
    return finish(lines)


def render_application(package: Any) -> str:
    lines = new_page("Application Reference")
    lines.extend(
        [
            "Use these objects to create an app, group routes by feature, and",
            "configure Quater's built-in docs and safety defaults.",
            "",
            "For the route model, read [Public API](/en/dev/api). For production",
            "settings, read [Security](/en/dev/security).",
            "",
            "```python",
            "from quater import AppConfig, CORSConfig, Quater, Resource, RouteGroup",
            "```",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "Quater",
        "The application object.",
        [
            "`Quater` owns the route registry, middleware, lifespan hooks, and",
            "server adapters. A route can stay HTTP-only, or it can opt into MCP",
            "and CLI surfaces with `tool=True` and `cli=True`.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "Quater")))
    lines.extend(
        validated_option_table(
            package, "Quater", None, "Constructor options", QUATER_OPTIONS
        )
    )
    lines.extend(
        [
            "### App state",
            "",
            "`app.state` is a [`State`](./request#symbol-state) container for",
            "resources that belong to the app instance. It is available from",
            "handlers as `request.app.state`.",
            "",
            "### Route decorators",
            "",
            "Use decorators for normal route registration. `get`, `post`, `put`,",
            "`patch`, and `delete` use the same options as `route`.",
            "",
        ]
    )
    lines.extend(signature_block(method_signature(package, "Quater", "route")))
    lines.extend(
        validated_option_table(
            package, "Quater", "route", "Route options", ROUTE_OPTIONS
        )
    )
    lines.extend(
        [
            "Descriptions matter for `tool=True` and `cli=True` routes. They are the",
            "text an agent or operator sees before deciding whether to call the",
            "operation.",
            "",
            "### Common app methods",
            "",
            "| Method | Use it for |",
            "| --- | --- |",
            "| `include(group)` | Include a "
            "[`RouteGroup`](#symbol-routegroup) in the app. |",
            "| `add_route(...)` | Register a route without decorator syntax. |",
            "| `before_request(...)` | Register global before-request middleware. |",
            "| `after_response(...)` | Register global after-response middleware. |",
            "| `around_request(...)` | Wrap the request handler pipeline. |",
            "| `exception_handler(...)` | Register a global exception handler. |",
            "| `on_startup(...)` / `on_shutdown(...)` | Register lifespan hooks. |",
            "| `startup()` / `shutdown()` | Run lifespan hooks manually in tests. |",
            "| `handle(request)` | Handle an in-process request. |",
            "| `validate_production()` | Fail fast on unsafe production config. |",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "RouteGroup",
        "A compile-time group for related routes.",
        [
            "A group lets you share a prefix, tags, auth, middleware, and exception",
            "handlers across a feature area. Included groups are flattened into",
            "normal routes before matching, so grouping does not add a router layer",
            "to the hot path.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "RouteGroup")))
    lines.extend(
        validated_option_table(
            package,
            "RouteGroup",
            None,
            "Constructor options",
            ROUTE_GROUP_OPTIONS,
        )
    )
    lines.extend(
        [
            "Use `app.include(group)` after all routes are declared. Quater locks the",
            "group after inclusion so routes cannot silently disappear later.",
            "",
            "Route groups expose the same route decorators as the app.",
            "",
        ]
    )
    lines.extend(signature_block(method_signature(package, "RouteGroup", "route")))
    lines.extend(
        validated_option_table(
            package,
            "RouteGroup",
            "route",
            "Group route options",
            GROUP_ROUTE_OPTIONS,
        )
    )
    lines.extend(
        [
            "The route options mean the same thing on",
            "[`RouteGroup`](#symbol-routegroup) as they do on",
            "[`Quater`](#symbol-quater). Group-level auth, resources, metadata, and",
            "middleware are merged into the final route before the app compiles",
            "routes.",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "AppConfig",
        "Immutable application configuration.",
        [
            "Most apps pass simple keyword overrides to",
            "[`Quater(...)`](#symbol-quater). Use `AppConfig` when you want to",
            "build configuration once and pass it around explicitly.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "AppConfig")))
    lines.extend(field_table(package, "AppConfig"))
    symbol_intro(
        lines,
        package,
        "CORSConfig",
        "Browser CORS policy.",
        [
            "CORS controls which browser origins may read responses. It is not an",
            "authentication system; use `auth=...`, `mcp_auth`, and `cli_auth` for",
            "access control.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "CORSConfig")))
    lines.extend(field_table(package, "CORSConfig"))
    symbol_intro(
        lines,
        package,
        "__version__",
        "Installed Quater version.",
        ["Use this for diagnostics or support output."],
    )
    lines.extend(code_block(f"__version__ = {attribute_value(package, '__version__')}"))
    lines.extend(
        type_section(
            (
                (
                    "SecurityMode",
                    "Literal config value: `strict`, `relaxed`, or `off`.",
                ),
                (
                    "MaxBodySize",
                    'Either bytes as `int` or a string such as `"2mb"`.',
                ),
                (
                    "Authenticate",
                    "Async auth hook. See "
                    "[Auth and Security](./auth#symbol-authrequest).",
                ),
                (
                    "ActionApproval",
                    "Async approval hook. See "
                    "[ActionApproval](./auth#symbol-actionapproval).",
                ),
                (
                    "AuditHook",
                    "Async MCP audit hook receiving "
                    "[ToolAuditEvent](./observability#symbol-toolauditevent).",
                ),
                (
                    "AccessLogHook",
                    "Async access-log hook. See "
                    "[Observability](./observability#symbol-accessloghook).",
                ),
                (
                    "BeforeMiddleware",
                    "Runs before the handler. It can short-circuit by returning "
                    "a response.",
                ),
                (
                    "AfterMiddleware",
                    "Runs after the handler and can adjust the response.",
                ),
                (
                    "AroundMiddleware",
                    "Wraps the handler pipeline for timing, tracing, or similar "
                    "cross-cutting behavior.",
                ),
                (
                    "ExceptionHandlerEntry",
                    "Internal wrapper for exception handlers passed through "
                    "decorators.",
                ),
            )
        )
    )
    return finish(lines)


def render_resources(package: Any) -> str:
    lines = new_page("Resources Reference")
    lines.extend(
        [
            "Use these objects when a handler needs an app-owned value, such as a",
            "database session, cache handle, tenant object, or request-scoped service.",
            "",
            "For the guide, read [Resources and Injection](/en/dev/resources).",
            "",
            "```python",
            "from quater import Resource",
            "```",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "Resource",
        "A request-scoped injectable value.",
        [
            "`Resource` wraps a provider callable and lets a route inject the",
            "provider result into a named handler parameter.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "Resource")))
    lines.extend(
        [
            "### Constructor options",
            "",
            "| Name | Type | Meaning |",
            "| --- | --- | --- |",
            "| `provider` | [`ResourceProvider[T]`](#type-resourceprovider) | "
            "Callable that creates the value. |",
            "| `scope` | [`ResourceScope`](#type-resourcescope) | "
            "Resource lifetime. Currently only `request` is supported. |",
            "| `name` | `str \\| None` | Optional name used in resource error "
            "messages. |",
            "",
            "### Provider forms",
            "",
            "The provider may accept no arguments:",
            "",
            "```python",
            "async def settings() -> Settings:",
            "    return Settings.from_env()",
            "```",
            "",
            "Or it may accept the current [`Request`](./request#symbol-request):",
            "",
            "```python",
            "async def current_tenant(request: Request) -> Tenant:",
            "    return await request.app.state.tenants.load(",
            '        request.headers.get("x-tenant-id")',
            "    )",
            "```",
            "",
            "The provider can return a plain value, an awaitable value, a sync or "
            "async",
            "context manager, or yield one value from a sync or async generator.",
            "`Resource` is generic: `Resource(provider)` carries the provider's "
            "resolved value type, so `await request.resolve(resource)` returns "
            "that value type.",
            "",
            "```python",
            "async def db_session(request: Request) -> AsyncIterator[DatabaseSession]:",
            "    async with request.app.state.database.session() as session:",
            "        yield session",
            "```",
            "",
            "Quater closes context-manager and generator resources after the handler",
            "finishes. Cleanup also runs when the handler raises.",
            "",
            "### Route usage",
            "",
            "```python",
            "db = Resource(db_session)",
            "",
            "",
            '@app.get("/orders/{order_id}", inject={"session": db})',
            "async def get_order(",
            "    order_id: str,",
            "    session: DatabaseSession,",
            ") -> dict[str, object]:",
            "    ...",
            "```",
            "",
            "Injected parameters are not included in OpenAPI request parameters, MCP",
            "input schemas, or CLI action schemas.",
            "",
            "## Types",
            "",
            "| Type | Meaning |",
            "| --- | --- |",
            '| <span id="type-resourceprovider"></span>`ResourceProvider` | '
            "Callable used by [`Resource`](#symbol-resource). It may return a "
            "plain value, awaitable value, sync or async context manager, or a "
            "sync or async generator that yields one value. |",
            '| <span id="type-resourcemap"></span>`ResourceMap` | Mapping of '
            "handler parameter name to [`Resource`](#symbol-resource). This is "
            "the type accepted by `inject`. |",
            '| <span id="type-resourcescope"></span>`ResourceScope` | Literal '
            "resource lifetime. Currently `request`. |",
        ]
    )
    return finish(lines)


def render_request(package: Any) -> str:
    lines = new_page("Request Reference")
    lines.extend(
        [
            "`Request` is the object to ask for when a handler needs headers,",
            "cookies, body access, auth context, or call-source information.",
            "",
            "For simple path/query/body parameters, let Quater bind the function",
            "arguments directly instead.",
            "",
            "```python",
            "from quater import Request, State",
            "```",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "Request",
        "Transport-neutral request data.",
        [
            "The same request object is used after RSGI, ASGI, WSGI, MCP, and CLI",
            "calls have been normalized into Quater's internal request flow.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "Request")))
    lines.extend(
        validated_option_table(
            package,
            "Request",
            None,
            "Constructor parameters",
            REQUEST_CONSTRUCTOR_OPTIONS,
        )
    )
    lines.extend(
        [
            "In normal app code, Quater creates the request and passes it to your",
            "handler. The table above matches the constructor signature. The sections",
            "below explain the objects you usually read from inside handlers.",
            "",
            "## Reading Request Data",
            "",
            "Most handlers use `request.headers`, `request.query`, `request.cookies`,",
            "`request.auth`, `request.context`, `await request.body()`, or",
            "`await request.json()`.",
            "",
            "Helper objects such as [`Headers`](#headers),",
            "[`QueryParams`](#queryparams), and [`Cookies`](#cookies) are not",
            "top-level public imports. Treat them as read-only request views.",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "State",
        "Attribute storage for application and request-local state.",
        [
            "`app.state` is shared by the application instance. Use it for",
            "resources created at startup, such as database pools or clients.",
            "`request.state` is created fresh for each request and is useful for",
            "middleware that needs to pass values to handlers.",
        ],
    )
    lines.extend(signature_block("State()"))
    lines.extend(
        [
            "Keep per-request data on `request.state`, not `app.state`. If you",
            "store shared objects on `app.state`, make sure those objects are safe",
            "for your concurrency and deployment model.",
            "",
            "```python",
            "@app.on_startup",
            "async def startup() -> None:",
            "    app.state.db = await open_database_pool()",
            "",
            '@app.get("/users/{id}")',
            "async def get_user(id: str, request: Request) -> dict[str, object]:",
            "    assert request.app is not None",
            "    user = await request.app.state.db.fetch_user(id)",
            '    return {"id": user.id}',
            "```",
            "",
            "## Call Context",
            "",
            "`RequestContext` is the small object stored at `request.context`. You do",
            "not need to create it in normal app code, but it is useful when a handler",
            "can be reached from more than one surface.",
            "",
            "`request.context` tells you how the handler was reached:",
            "",
            '- `source="api"` for normal HTTP routes.',
            '- `source="mcp"` for MCP protocol and tool calls.',
            '- `source="cli"` for Quater CLI actions.',
            '- `entrypoint="server"` for hosted calls.',
            '- `entrypoint="local"` for local CLI calls.',
            "",
            "```python",
            "async def whoami(request: Request) -> dict[str, object]:",
            "    return {",
            '        "source": request.context.source,',
            '        "entrypoint": request.context.entrypoint,',
            '        "subject": request.auth.subject if request.auth else None,',
            "    }",
            "```",
            "",
            "Context fields:",
            "",
            "| Field | Type | Meaning |",
            "| --- | --- | --- |",
            context_row(
                "source",
                '"api" | "mcp" | "cli"',
                "Which surface reached the handler.",
            ),
            context_row(
                "entrypoint",
                '"server" | "local"',
                "Hosted request or local CLI call.",
            ),
            "| `request_id` | `str \\| None` | Correlation id assigned by Quater. |",
            "| `tool_name` | `str \\| None` | MCP tool name for tool calls. |",
            "| `action_name` | `str \\| None` | CLI action name for action calls. |",
            "",
            "## Header, Query, and Cookie Views",
            "",
            "These objects behave like small read-only mappings. You can use common",
            "mapping methods such as `get()`, `in`, iteration, and `[...]` lookup.",
            "",
            "### Headers",
            "",
            "`request.headers` is case-insensitive. Header names are normalized for",
            "lookup, so these are equivalent:",
            "",
            "```python",
            'request.headers.get("authorization")',
            'request.headers.get("Authorization")',
            "```",
            "",
            "Use `get_all(name)` when a header may appear more than once. Use `.raw`",
            "when you need the normalized `(name, value)` pairs.",
            "",
            "```python",
            'authorization = request.headers.get("authorization")',
            'set_cookie_headers = request.headers.get_all("set-cookie")',
            "raw_headers = request.headers.raw",
            "```",
            "",
            "### QueryParams",
            "",
            "`request.query` is a parsed query-string mapping. Normal lookup returns",
            "the last value for a repeated key, which matches normal dictionary",
            "behavior. Use `get_all(name)` when repeated query parameters matter.",
            "",
            "```python",
            "# /search?tag=python&tag=api",
            'first_value = request.query.get("tag")',
            'all_values = request.query.get_all("tag")',
            "```",
            "",
            "Use `.raw` when you need all `(name, value)` pairs in order.",
            "",
            "### Cookies",
            "",
            "`request.cookies` is a parsed mapping of cookie names to cookie values.",
            "Use `.get()` when a cookie is optional.",
            "",
            "```python",
            'session_id = request.cookies.get("session")',
            "```",
            "",
            "### AuthContext",
            "",
            "`request.auth` is either `None` or the",
            "[`AuthContext`](./auth#symbol-authcontext) returned by the route",
            "auth hook. Always check it before reading `subject`.",
            "",
            "```python",
            "subject = request.auth.subject if request.auth else None",
            "```",
            "",
        ]
    )
    lines.extend(
        type_section(
            (
                (
                    "State",
                    "Attribute container exposed as `app.state` and `request.state`.",
                ),
                (
                    "Quater",
                    "Application object available as `request.app` after a "
                    "request enters an app.",
                ),
                (
                    "HeaderItems",
                    "`(name, value)` header pairs. Names and values may be "
                    "`str` or `bytes`.",
                ),
                (
                    "RequestBody",
                    "`bytes`, an async body reader, or `None`. App handlers "
                    "usually use `await request.body()`.",
                ),
                (
                    "AuthContext",
                    "Auth result returned by a route auth hook. See "
                    "[AuthContext](./auth#symbol-authcontext).",
                ),
                (
                    "RequestContext",
                    "Call-source context explained in [Call Context](#call-context).",
                ),
                (
                    "Headers",
                    "Read-only, case-insensitive header view available as "
                    "`request.headers`.",
                ),
                (
                    "QueryParams",
                    "Read-only query-string view available as `request.query`.",
                ),
                (
                    "Cookies",
                    "Read-only cookie mapping available as `request.cookies`.",
                ),
            )
        )
    )
    return finish(lines)


def render_parameters(package: Any) -> str:
    lines = new_page("Parameter Reference")
    lines.extend(
        [
            "Use parameter markers when handler arguments need explicit request",
            "locations, aliases, defaults, or generated schema descriptions.",
            "",
            "For the binding model, read [Public API](/en/dev/api#parameters).",
            "For raw request access, read [Request](./request).",
            "",
            "```python",
            "from quater import Body, Cookie, File, Form, Header, Path, Query",
            "```",
            "",
            "Markers can be used as defaults or inside `typing.Annotated`. The",
            "default form is shorter. `Annotated` keeps the Python default separate.",
            "`Query`, `Header`, `Cookie`, and `Form` bind scalar values only:",
            "`str`, `int`, `float`, or `bool`. Use `Body` for structured JSON",
            "input and `File` for multipart file uploads.",
            "",
            "```python",
            "from typing import Annotated",
            "",
            "from quater import Query",
            "",
            "async def search(",
            '    q: str = Query(description="Search text"),',
            '    page: Annotated[int, Query(alias="p")] = 1,',
            ") -> dict[str, object]:",
            '    return {"q": q, "page": page}',
            "```",
            "",
        ]
    )
    for symbol in page_symbols("parameters"):
        summary, details = PARAMETER_DOCS[symbol]
        symbol_intro(lines, package, symbol, summary, details)
        lines.extend(signature_block(callable_signature(package, symbol)))
        lines.extend(
            validated_function_option_table(
                package,
                symbol,
                "Parameters",
                PARAMETER_OPTIONS[symbol],
            )
        )
    lines.extend(
        [
            "## Action and Tool Names",
            "",
            "Aliases describe the HTTP wire name. MCP tools and CLI actions keep the",
            "Python handler parameter name as the action argument name, except for",
            "`Body(alias=...)`, which renames the body action argument. That keeps",
            '`Header(alias="X-Request-ID")` readable in OpenAPI without forcing',
            "agents to send a JSON key named `X-Request-ID`.",
            "",
        ]
    )
    return finish(lines)


def render_responses(package: Any) -> str:
    lines = new_page("Responses Reference")
    lines.extend(
        [
            "Most handlers do not need to create response objects. Return plain Python",
            "values when that is enough; use explicit response classes when you need",
            "status codes, headers, streaming, redirects, or a specific content type.",
            "",
            "```python",
            "from quater import JSONResponse, RedirectResponse, StreamResponse",
            "```",
            "",
            "## Automatic Return Values",
            "",
            "| Handler returns | Quater sends |",
            "| --- | --- |",
            "| `dict`, `list`, dataclass, `msgspec.Struct` | JSON response |",
            "| `str` | UTF-8 text response |",
            "| `bytes`, `bytearray`, `memoryview` | Byte response |",
            "| `None` | Empty `204` response |",
            "| [`Response`](#symbol-response) instance | Sent as-is |",
            "",
            "## Response Classes",
            "",
        ]
    )
    for symbol in page_symbols("responses"):
        symbol_intro(lines, package, symbol, RESPONSE_DOCS[symbol], [])
        lines.extend(signature_block(class_signature(package, symbol)))
        lines.extend(
            validated_option_table(
                package,
                symbol,
                None,
                "Parameters",
                RESPONSE_OPTIONS[symbol],
            )
        )
    lines.extend(
        [
            "## Cookie helpers",
            "",
            "Both helpers are available on every response class.",
            "",
            "### `set_cookie`",
            "",
        ]
    )
    lines.extend(signature_block(method_signature(package, "Response", "set_cookie")))
    lines.extend(
        validated_option_table(
            package,
            "Response",
            "set_cookie",
            "Parameters",
            SET_COOKIE_OPTIONS,
        )
    )
    lines.extend(
        [
            "### `delete_cookie`",
            "",
        ]
    )
    lines.extend(
        signature_block(method_signature(package, "Response", "delete_cookie"))
    )
    lines.extend(
        validated_option_table(
            package,
            "Response",
            "delete_cookie",
            "Parameters",
            DELETE_COOKIE_OPTIONS,
        )
    )
    lines.extend(
        type_section(
            (
                (
                    "HeaderItems",
                    "`(name, value)` header pairs. See "
                    "[Request headers](./request#headers).",
                ),
                (
                    "ResponseBody",
                    "Bytes-like value accepted by "
                    "[`BytesResponse`](#symbol-bytesresponse).",
                ),
                ("AsyncIterable[bytes]", "Async stream of response chunks."),
            )
        )
    )
    return finish(lines)


def render_auth(package: Any) -> str:
    lines = new_page("Auth and Security Reference")
    lines.extend(
        [
            "Quater applies auth at the app boundary. Pass one or more",
            "`AuthConfig` objects to `Quater(auth=[...])`; each config covers one",
            "or more surfaces (`api`, `mcp`, `cli`) and each surface is covered by",
            "at most one config.",
            "",
            "- Surface-wide auth: pass `AuthConfig(fn, surfaces=[...])` to"
            " `Quater(auth=[...])`.",
            "- Route-level exceptions: pass `public=True` (or an iterable of",
            "  surfaces) on a route or route group to bypass app-level auth.",
            "",
            "The same authenticator shape runs on every covered surface. For the full",
            "security model, read [Security](/en/dev/security).",
            "",
            "```python",
            "from quater import (",
            "    AuthConfig,",
            "    AuthContext,",
            "    HTTPError,",
            "    ImproperlyConfigured,",
            "    SignedCookieSigner,",
            ")",
            "```",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "AuthConfig",
        "One authenticator bound to one or more request surfaces.",
        [
            "Pass a list of `AuthConfig` objects to `Quater(auth=...)`. Each surface",
            "(`api`, `mcp`, `cli`) may be covered by at most one `AuthConfig`.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "AuthConfig")))
    lines.extend(field_table(package, "AuthConfig"))
    symbol_intro(
        lines,
        package,
        "AuthContext",
        "Authenticated subject returned by an auth hook.",
        [
            "Return `None` from an auth hook when the request is not authenticated.",
            "Return `AuthContext` when it is authenticated.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "AuthContext")))
    lines.extend(field_table(package, "AuthContext"))
    symbol_intro(
        lines,
        package,
        "ApprovalRequest",
        "Input passed to the approval hook for protected tools and actions.",
        [
            "Use this when a route has `needs_approval=True`. Approval is separate",
            "from auth: auth identifies the caller, approval confirms a sensitive",
            "operation should run.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "ApprovalRequest")))
    lines.extend(field_table(package, "ApprovalRequest"))
    symbol_intro(
        lines,
        package,
        "ActionApproval",
        "Callable type for approval hooks.",
        [
            "Return `True` to allow the protected operation.",
            "Return `False` to deny it.",
        ],
    )
    lines.extend(
        code_block(f"ActionApproval = {attribute_value(package, 'ActionApproval')}")
    )
    symbol_intro(
        lines,
        package,
        "HTTPError",
        "Exception that becomes an HTTP-style error response.",
        ["Raise it when app code needs to stop with a specific status and detail."],
    )
    lines.extend(signature_block(class_signature(package, "HTTPError")))
    lines.extend(
        validated_option_table(
            package,
            "HTTPError",
            None,
            "Constructor parameters",
            HTTP_ERROR_OPTIONS,
        )
    )
    symbol_intro(
        lines,
        package,
        "ImproperlyConfigured",
        "Exception raised for invalid framework configuration.",
        [
            "Catch this when app setup should fail loudly before serving traffic.",
            "`ConfigurationError` remains as a backward-compatible subclass.",
        ],
    )
    lines.extend(code_block('raise ImproperlyConfigured("bad setup")'))
    symbol_intro(
        lines,
        package,
        "SignedCookieSigner",
        "HMAC signer for small cookie values.",
        [
            "Use fallback secrets during key rotation. Verification uses constant-time",
            "signature comparison.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "SignedCookieSigner")))
    lines.extend(
        validated_option_table(
            package,
            "SignedCookieSigner",
            None,
            "Constructor parameters",
            SIGNED_COOKIE_SIGNER_OPTIONS,
        )
    )
    lines.extend(
        [
            "Common methods:",
            "",
            "| Method | Use it for |",
            "| --- | --- |",
            "| `sign(value)` | Return a signed string safe to store in a cookie. |",
            "| `verify(signed_value)` | Return the original value, or `None`. |",
            "",
        ]
    )
    lines.extend(
        type_section(
            (
                (
                    "RequestContext",
                    "Call-source context. See [Request](./request#call-context).",
                ),
                (
                    "Authenticator",
                    "Async callable that receives a "
                    "[`Request`](./request#symbol-request) and returns an "
                    "[`AuthContext`](#symbol-authcontext) or `None`.",
                ),
                ("SecretValue", "`str` or `bytes` cookie signing secret."),
            )
        )
    )
    return finish(lines)


def render_observability(package: Any) -> str:
    lines = new_page("Observability Reference")
    lines.extend(
        [
            "These types are used by access logging and MCP tool auditing. They are",
            "small by design so apps can send them to logs, metrics, or tracing",
            "systems without depending on Quater internals.",
            "",
            "```python",
            "from quater import AccessLogEvent, AccessLogHook, ToolAuditEvent",
            "```",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "AccessLogEvent",
        "Structured event emitted after a request is handled.",
        ["Configure `access_logger=` on `Quater(...)` to receive these events."],
    )
    lines.extend(signature_block(class_signature(package, "AccessLogEvent")))
    lines.extend(field_table(package, "AccessLogEvent"))
    lines.extend(
        [
            "`AccessLogEvent.to_dict()` returns a plain dictionary for loggers that",
            "expect JSON-like data.",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "AccessLogHook",
        "Callable type for access-log hooks.",
        ["The hook is async so it can write to async logging or telemetry clients."],
    )
    lines.extend(
        code_block(f"AccessLogHook = {attribute_value(package, 'AccessLogHook')}")
    )
    symbol_intro(
        lines,
        package,
        "ToolAuditEvent",
        "Structured event emitted for MCP tool calls.",
        [
            "Tool arguments are redacted before the event reaches your audit hook.",
            "Use this for visibility, not for authorization.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "ToolAuditEvent")))
    lines.extend(field_table(package, "ToolAuditEvent"))
    return finish(lines)


def render_testing(package: Any) -> str:
    lines = new_page("Testing Reference")
    lines.extend(
        [
            "Use the in-process clients to test Quater apps without starting Granian",
            "or opening a socket. This keeps tests fast and makes auth, cookies,",
            "lifespan hooks, MCP tools, and response bodies straightforward to assert.",
            "",
            "For examples, read the [Testing guide](/en/dev/testing).",
            "",
            "```python",
            "from quater import CliTestClient, MCPTestClient, TestClient, TestResponse",
            "```",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "TestClient",
        "Async in-process client for HTTP-style tests.",
        ["Use it with `async with` when your app has startup or shutdown hooks."],
    )
    lines.extend(signature_block(class_signature(package, "TestClient")))
    lines.extend(
        validated_option_table(
            package,
            "TestClient",
            None,
            "Constructor parameters",
            TEST_CLIENT_OPTIONS,
        )
    )
    lines.extend(
        [
            "Common methods:",
            "",
            "| Method | Use it for |",
            "| --- | --- |",
            "| `request(method, path, ...)` | Send any method. |",
            "| `get`, `post`, `put`, `patch`, `delete` | Convenience methods. |",
            "| `set_cookie(name, value)` | Store a cookie for later requests. |",
            "| `clear_cookies()` | Clear stored cookies. |",
            "| `startup()` / `shutdown()` | Run lifespan manually. |",
            "",
        ]
    )
    lines.extend(signature_block(method_signature(package, "TestClient", "request")))
    lines.extend(
        validated_option_table(
            package,
            "TestClient",
            "request",
            "`request()` parameters",
            TEST_CLIENT_REQUEST_OPTIONS,
        )
    )
    symbol_intro(
        lines,
        package,
        "TestResponse",
        "Response returned by [`TestClient`](#symbol-testclient).",
        ["It stores the collected body, headers, status code, and JSON helpers."],
    )
    lines.extend(signature_block(class_signature(package, "TestResponse")))
    lines.extend(
        validated_option_table(
            package,
            "TestResponse",
            None,
            "Constructor parameters",
            TEST_RESPONSE_OPTIONS,
        )
    )
    lines.extend(
        [
            "| Property or method | What it returns |",
            "| --- | --- |",
            "| `status_code` | Integer response status. |",
            "| `headers` | Parsed response headers. |",
            "| `body` | Raw response bytes. |",
            "| `text` | UTF-8 decoded body. |",
            "| `is_success` | `True` for `2xx` and `3xx` responses. |",
            "| `json()` | Parsed JSON body. |",
            "",
        ]
    )
    symbol_intro(
        lines,
        package,
        "MCPTestClient",
        "Small JSON-RPC helper bound to a [`TestClient`](#symbol-testclient).",
        [
            "Use `client.mcp` in tests. It sends MCP requests through the same app",
            "pipeline as a real MCP client.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "MCPTestClient")))
    lines.extend(
        validated_option_table(
            package,
            "MCPTestClient",
            None,
            "Constructor parameters",
            MCP_TEST_CLIENT_OPTIONS,
        )
    )
    lines.extend(
        [
            "Common methods:",
            "",
            "| Method | Use it for |",
            "| --- | --- |",
            "| `initialize(...)` | Send MCP `initialize`. |",
            "| `tools_list(...)` | List exposed tools. |",
            "| `tools_call(name, arguments, ...)` | Call an exposed tool. |",
            "| `request(payload, ...)` | Send a custom JSON-RPC payload. |",
            "",
        ]
    )
    lines.extend(
        signature_block(method_signature(package, "MCPTestClient", "tools_call"))
    )
    lines.extend(
        validated_option_table(
            package,
            "MCPTestClient",
            "tools_call",
            "`tools_call()` parameters",
            MCP_TOOLS_CALL_OPTIONS,
        )
    )
    symbol_intro(
        lines,
        package,
        "CliTestClient",
        "Remote-action helper bound to a [`TestClient`](#symbol-testclient).",
        [
            "Use `client.cli` in tests. It calls actions and reads the action",
            "manifest through the same remote-action endpoints as the Quater CLI.",
        ],
    )
    lines.extend(signature_block(class_signature(package, "CliTestClient")))
    lines.extend(
        validated_option_table(
            package,
            "CliTestClient",
            None,
            "Constructor parameters",
            CLI_TEST_CLIENT_OPTIONS,
        )
    )
    lines.extend(
        [
            "Common methods:",
            "",
            "| Method | Use it for |",
            "| --- | --- |",
            "| `call(action, arguments, ...)` | Call an exposed CLI action. |",
            "| `manifest(...)` | Read the action manifest. |",
            "",
            "Both methods return the raw [`TestResponse`](#symbol-testresponse). A",
            "successful action body is the `{ok, status_code, body}` envelope, and a",
            "`dry_run=True` call returns the preflight payload instead of running the",
            "handler.",
            "",
        ]
    )
    lines.extend(signature_block(method_signature(package, "CliTestClient", "call")))
    lines.extend(
        validated_option_table(
            package,
            "CliTestClient",
            "call",
            "`call()` parameters",
            CLI_CALL_OPTIONS,
        )
    )
    lines.extend(
        type_section(
            (
                (
                    "HeaderItems",
                    "`(name, value)` header pairs. See "
                    "[Request headers](./request#headers).",
                ),
                (
                    "QueryParams",
                    "Mapping or sequence accepted by "
                    "[`TestClient`](#symbol-testclient).",
                ),
                (
                    "RequestContent",
                    "`bytes`, `bytearray`, `memoryview`, or `str` request body "
                    "content.",
                ),
                ("JSONRPCID", "MCP JSON-RPC request id, either `str` or `int`."),
            )
        )
    )
    return finish(lines)
