# Public API

This is the surface Quater expects users to import for the first release.
Everything else can still move while the framework is pre-release.

Use top-level imports for normal app code:

```python
from quater import (
    ActionApproval,
    AppConfig,
    ApprovalRequest,
    AuthContext,
    AuthRequest,
    BytesResponse,
    CORSConfig,
    EmptyResponse,
    HTMLResponse,
    HTTPError,
    JSONResponse,
    MCPTestClient,
    Quater,
    RedirectResponse,
    Request,
    Response,
    SignedCookieSigner,
    StreamResponse,
    TestClient,
    TestResponse,
    TextResponse,
    ToolAuditEvent,
)
```

## App

`Quater()` is the application object.

```python
app = Quater(
    allowed_hosts=["api.example.com"],
    max_body_size="2mb",
    docs_path="/docs",
    openapi_path="/openapi.json",
    mcp_docs_path="/mcp/docs",
    mcp_auth=authenticate,
    cli_auth=authenticate,
)
```

The snippet assumes you already defined `authenticate`. For an app with no MCP
tools, omit `mcp_auth`. For an app with no CLI actions, omit `cli_auth`.

Stable constructor options:

- `name`
- `config`
- `debug`
- `security`
- `allowed_hosts`
- `trusted_proxies`
- `max_body_size`
- `cors`
- `content_security_policy`
- `docs_path`
- `openapi_path`
- `mcp_docs_path`
- `mcp_allowed_origins`
- `mcp_auth`
- `mcp_audit`
- `cli_auth`
- `action_approval`

The MCP JSON-RPC endpoint is always `/mcp`. There is no `mcp_path` option. If
an app exposes tools, `mcp_auth` is required.

If an app exposes `cli=True` routes, `cli_auth` is required. If any exposed
route uses `needs_approval=True`, `action_approval` is required.

## Routes

Route decorators are the main API:

```python
@app.get("/items/{id:int}")
async def get_item(id: int) -> dict[str, int]:
    return {"id": id}
```

Available decorators:

- `app.get`
- `app.post`
- `app.put`
- `app.patch`
- `app.delete`
- `app.route`

Stable decorator options:

- `name`
- `description`
- `tool`
- `cli`
- `needs_approval`
- `auth`
- `metadata`
- `before`
- `after`
- `around`
- `exception_handlers`

`tool=True` exposes the route through MCP. Tool routes must have a useful
description, either through `description=` or the handler docstring. The app
must also be created with `mcp_auth`.

`cli=True` exposes the route through Quater actions. CLI action routes also need
a useful description and the app must be created with `cli_auth`.

`needs_approval=True` can be used with `tool=True` or `cli=True`. It requires an
`action_approval` hook on the app.

## Request And Context

Use `Request` when the handler needs headers, body access, auth, or the call
source.

```python
@app.get("/whoami")
async def whoami(request: Request) -> dict[str, object]:
    return {
        "source": request.context.source,
        "tool": request.context.tool_name,
    }
```

`request.context.source` is:

- `"api"` for normal HTTP calls.
- `"mcp"` for MCP protocol requests such as `initialize` and `tools/list`.
- `"tool"` for MCP `tools/call`.
- `"local_cli"` for local Quater CLI action calls.
- `"remote_cli"` for hosted Quater CLI action calls.

`request.context.tool_name` is set for MCP tool calls.
`request.context.action_name` is set for MCP tool calls and CLI action calls.

## Auth

Auth hooks receive `AuthRequest` and return `AuthContext | None`.

```python
async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="demo-user")
```

Attach the hook per route:

```python
@app.get("/me", auth=authenticate)
async def me(request: Request) -> dict[str, str]:
    assert request.auth is not None
    return {"subject": request.auth.subject}
```

For MCP tools, the same hook can also be passed as `mcp_auth`:

```python
app = Quater(mcp_auth=authenticate)
```

`mcp_auth` protects MCP protocol requests and `/mcp/docs`. Route `auth=` still
protects individual handlers. If both point to the same function, Quater still
runs route auth against the handler route so path-based policies cannot be
accidentally skipped.

For CLI actions, pass an auth hook as `cli_auth`:

```python
app = Quater(cli_auth=authenticate)
```

`cli_auth` protects local action discovery, local action execution, remote
action discovery, and remote action execution. Route `auth=` still protects
individual handlers.

## Actions and Approval

Use `cli=True` for routes that should be callable from the Quater CLI:

```python
app = Quater(cli_auth=authenticate)


@app.get("/orders/{order_id}", cli=True, description="Fetch one order by id.")
async def get_order(order_id: str) -> dict[str, str]:
    return {"order_id": order_id}
```

Use `needs_approval=True` for exposed actions that require a second check before
execution:

```python
from quater import ApprovalRequest, Quater


async def approve_action(ctx: ApprovalRequest) -> bool:
    return ctx.token == "approve-local"


app = Quater(
    cli_auth=authenticate,
    action_approval=approve_action,
)


@app.patch(
    "/orders/{order_id}/status",
    cli=True,
    needs_approval=True,
    description="Update an order status.",
)
async def update_order_status(order_id: str, status: str) -> dict[str, str]:
    return {"order_id": order_id, "status": status}
```

`ApprovalRequest` includes:

- `action`
- `arguments_hash`
- `token`
- `auth`
- `context`

Quater validates action arguments before calling the approval hook. Dry-run
returns the same argument hash without calling the handler or approval hook.

## Responses

Use response objects when you need explicit status, headers, content type, or
streaming:

```python
from quater import JSONResponse, StreamResponse, TextResponse
```

Plain return values still cover the common case:

- `dict`, `list`, `tuple`, `bool`, `int`, and `float` become JSON.
- dataclass instances and `msgspec.Struct` instances become JSON.
- `str` becomes `TextResponse`.
- `bytes` becomes `BytesResponse`.
- `None` becomes `204 No Content`.

## Testing

Use `TestClient` to test a Quater app in process. It calls `app.handle()`
directly, so tests do not need Granian, ASGI, WSGI, or a listening port.

```python
from quater import Quater, TestClient

app = Quater()


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


async def test_health() -> None:
    async with TestClient(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

The async context manager runs startup and shutdown hooks. The client keeps a
small cookie jar, supports `params=`, `headers=`, `cookies=`, `json=`, and
`content=`, and collects streaming responses into `response.body`.

MCP helpers are available under `client.mcp`. The attribute is an
`MCPTestClient`; most tests should use it through `TestClient` instead of
constructing it directly.

```python
response = await client.mcp.tools_call(
    "get_user",
    {"id": 7},
    token="demo-token",
    origin="https://client.example",
)
```

For testing patterns across auth, cookies, streams, and MCP tools, read the
[Testing guide](/en/latest/testing).

## Config Helpers

`CORSConfig` is the public CORS helper:

```python
app = Quater(
    cors=CORSConfig(allowed_origins=("https://app.example.com",)),
)
```

`AppConfig` is useful when several app instances should share one base config:

```python
base = AppConfig(allowed_hosts=("api.example.com",))
app = Quater(config=base)
```

`SignedCookieSigner` signs small cookie values with HMAC:

```python
signer = SignedCookieSigner("new-secret", fallback_secrets=["old-secret"])
cookie_value = signer.sign("user_123")
```

## MCP Audit

Use `ToolAuditEvent` to type an audit hook:

```python
async def audit(event: ToolAuditEvent) -> None:
    print(event.tool_name, event.subject, event.success)


app = Quater(
    mcp_auth=authenticate,
    mcp_audit=audit,
)
```

Tool arguments are redacted before they reach the hook.

## Advanced Imports

These modules are public, but most apps do not need them:

- `quater.typing` for `Authenticate`, `LifespanHook`, and `RequestContext`.
- `quater.exceptions` for specific framework exceptions.
- `quater.adapters` when a server wants an explicit adapter object.

Do not import `quater._router`, `quater.docs.*`, or `quater.tools.registry` from
application code. Those are framework internals for now.
