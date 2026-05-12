# Quickstart

Start with one object.

```python
from quater import Quater, Request

app = Quater()


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/echo")
async def echo(request: Request) -> dict[str, object]:
    return {"received": await request.json()}
```

Run it:

```bash
quater dev main.py
```

Reload is already enabled in development. You can be explicit if you want:

```bash
quater dev main.py --reload
```

Access logs also come from Granian and are enabled by default. Disable them with
`--no-access-log` when you want quieter local output:

```bash
quater dev main.py --no-access-log
```

`quater dev` uses RSGI and reload by default. If you start it without a target,
Quater looks for common app files such as `main.py` and `app.py`.

## Generated Docs

Quater serves docs by default:

- `/docs` for Swagger UI.
- `/openapi.json` for OpenAPI.
- `/mcp/docs` for exposed MCP tools. It is empty until you expose a tool.

If you expose tools, pass `mcp_auth` when creating the app. Quater uses that
hook for MCP protocol requests and the MCP docs page.

Set a path to `None` to turn that page off:

```python
app = Quater(
    docs_path=None,
    openapi_path=None,
    mcp_docs_path=None,
)
```

If `docs_path` is enabled, `openapi_path` must also be enabled. Swagger UI needs
the JSON document to render anything useful.

## Binding

Path parameters come from route patterns:

```python
@app.get("/users/{id:int}")
async def get_user(id: int) -> dict[str, int]:
    return {"id": id}
```

Simple scalar parameters come from the query string:

```python
@app.get("/search")
async def search(q: str, page: int = 1) -> dict[str, object]:
    return {"q": q, "page": page}
```

Complex parameters come from the JSON body. `msgspec.Struct` is the best fit when
you care about speed and typed input.

```python
import msgspec


class UserIn(msgspec.Struct):
    name: str
    age: int


@app.post("/users")
async def create_user(user: UserIn) -> dict[str, object]:
    return {"name": user.name, "age": user.age}
```

## First MCP Tool

Expose a route as a tool with `tool=True`. Tool descriptions are required because
agents read them during `tools/list`.

```python
from quater import AuthContext, AuthRequest, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="demo-user")


app = Quater(mcp_auth=authenticate)


@app.get(
    "/users/{id:int}",
    tool=True,
    auth=authenticate,
    description="Fetch one user.",
)
async def get_user(id: int, request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {"id": id, "subject": request.auth.subject}
```

`mcp_auth` protects the MCP endpoint itself. Route `auth=` protects the handler.
When both use the same function, Quater still runs route auth against the
handler route.

## First CLI Action

Expose a route to the Quater CLI with `cli=True`. CLI actions are useful for
operator workflows, local scripts, and remote administration. They use the same
handler as HTTP, but they are protected by `cli_auth`.

```python
from quater import AuthContext, AuthRequest, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer admin-token":
        return None
    return AuthContext(subject="admin")


app = Quater(cli_auth=authenticate)


@app.get(
    "/orders/{order_id}",
    cli=True,
    description="Fetch one order by id.",
)
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {
        "order_id": order_id,
        "source": request.context.source,
        "subject": request.auth.subject,
    }
```

Run it locally without starting a server:

```bash
QUATER_APP=main:app quater --token admin-token actions list
QUATER_APP=main:app quater --token admin-token actions describe get_order
QUATER_APP=main:app quater --token admin-token call get_order --order-id ord_1001
```

For a hosted app, connect once and call the same action remotely:

```bash
quater connect store https://api.example.com --token admin-token
quater actions search store order
quater actions describe store get_order
quater call store get_order --order-id ord_1001
```

Use `--dry-run` before sensitive calls. Dry-run validates the inputs, shows the
method and path that would be called, and returns an argument hash without
running the handler.

::: tip More on actions
The full action guide covers remote discovery, JSON body arguments,
approval-protected actions, and production `quater run` behavior:
[Actions and CLI](/en/latest/actions).
:::

## Responses

Handlers can return plain values or response objects:

- `dict`, `list`, `tuple`, non-string scalar values, dataclasses, and
  `msgspec.Struct` values become JSON.
- `str` becomes text.
- `bytes` becomes bytes.
- `None` becomes `204 No Content`.
- `Response` subclasses are returned directly.

## Adapters

RSGI is the primary path because it maps directly to Granian's fast Python
interface.

```bash
quater dev main.py --interface rsgi
```

ASGI and WSGI use the same `Quater.handle()` core:

```bash
quater dev asgi_compat.py --interface asgi
quater dev wsgi_compat.py --interface wsgi
```

You can also pass the explicit adapter if a server wants it:

- `app.rsgi`
- `app.asgi`
- `app.wsgi`

WebSocket scopes are rejected for now. Quater does not expose a framework-level
WebSocket API in the MVP.
