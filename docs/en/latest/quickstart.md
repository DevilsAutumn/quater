# Quickstart

This page gets you from a clean Python project to a running Quater app. You will
build one backend operation and call it as a normal API, an AI-agent tool, and
an operator command.

## Prerequisites

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) installed.
The examples use `main.py` in an empty directory.

The example is intentionally small, but it shows the reason Quater exists: the
same backend work should not need one implementation for the app, another for
agents, and another for internal operations.

## Install

```bash
uv init quater-demo
cd quater-demo
uv add quater
```

## A Working App

Create `main.py`:

```python
from quater import AuthContext, AuthRequest, HTTPError, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="cust_123")


app = Quater(mcp_auth=authenticate, cli_auth=authenticate)

ORDERS: dict[str, dict[str, object]] = {
    "ord_1001": {"id": "ord_1001", "status": "paid", "total": 42.5}
}


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get(
    "/orders/{order_id}",
    tool=True,
    cli=True,
    auth=authenticate,
    description="Fetch one order by id.",
)
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPError("Order not found", status_code=404)
    assert request.auth is not None
    return {**order, "subject": request.auth.subject, "source": request.context.source}
```

Run it:

```bash
uv run quater dev main.py
```

Expected output:

```text
[INFO] Starting granian
[INFO] Listening at: http://127.0.0.1:8000
```

`quater dev` uses [Granian](https://github.com/emmett-framework/granian) with
RSGI by default, enables reload, and enables access logs.

## Call HTTP

```bash
curl -H "Authorization: Bearer demo-token" \
  http://127.0.0.1:8000/orders/ord_1001
```

Expected response:

```json
{
  "id": "ord_1001",
  "status": "paid",
  "total": 42.5,
  "subject": "cust_123",
  "source": "api"
}
```

Try the missing-token path:

```bash
curl -i http://127.0.0.1:8000/orders/ord_1001
```

Expected response:

```text
HTTP/1.1 401 Unauthorized

Unauthorized
```

## Call The Local CLI

Local CLI calls import the app in process. They do not need a running server.

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=demo-token
uv run quater actions list
uv run quater actions describe get_order
uv run quater call get_order --order-id ord_1001
```

Expected action list:

```text
get_order
  Fetch one order by id.
```

Expected call output:

```json
{
  "id": "ord_1001",
  "status": "paid",
  "total": 42.5,
  "subject": "cust_123",
  "source": "cli"
}
```

## Call The MCP Tool

MCP (Model Context Protocol) lets AI agents discover and call tools over HTTP.
Quater uses the route metadata to expose selected routes as MCP tools. Read the
protocol background at [modelcontextprotocol.io](https://modelcontextprotocol.io/).

The MCP endpoint is:

```text
POST /mcp
```

Tool calls must send auth on every request:

```json
{
  "mcpServers": {
    "quater-demo": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer demo-token"
      }
    }
  }
}
```

`initialize` does not create a Quater session. If the token expires later, the
next `tools/list` or `tools/call` fails with `401 Unauthorized`.

## Binding Rules

Quater binds handler parameters by type and marker:

- `Request` receives the normalized request object.
- `Resource` values come from `inject={...}`.
- `Path`, `Query`, `Body`, `Form`, `File`, `Header`, and `Cookie` markers
  choose a source.
- Route path names bind path parameters.
- Scalar values bind query parameters.
- Structured values bind JSON bodies.

Use [`msgspec.Struct`](https://jcristharif.com/msgspec/) when you want typed,
validated JSON input with Quater's fast JSON path. Plain `dict` works for
dynamic responses or data that does not need validation.

Use `Form` and `File` when a route must accept browser form posts or multipart
uploads. Form fields bind scalar values; file fields bind `UploadFile` or
`bytes`.

```python
import msgspec
from quater import Body, Quater


class UpdateOrder(msgspec.Struct):
    status: str
    notify_customer: bool = False


app = Quater()


@app.patch("/orders/{order_id}")
async def update_order(
    order_id: str,
    payload: UpdateOrder = Body(description="New order state."),
) -> dict[str, object]:
    return {"order_id": order_id, "status": payload.status}
```

Expected JSON body:

```json
{
  "payload": {
    "status": "shipped",
    "notify_customer": true
  }
}
```

## Generated Docs

Quater enables docs by default:

- `/docs` renders Swagger UI.
- `/openapi.json` returns an [OpenAPI](https://swagger.io/specification/) document.
- `/mcp/docs` shows human-readable MCP tool docs.

Disable docs by setting paths to `None`:

```python
app = Quater(
    docs_path=None,
    openapi_path=None,
    mcp_docs_path=None,
)
```

If `docs_path` is enabled, `openapi_path` must also be enabled.

## Choosing RSGI, ASGI, Or WSGI

RSGI is Granian's native interface and Quater's primary path. Choose it unless
your deployment platform requires something else.

ASGI and WSGI call the same `Quater.handle()` core through adapter layers. Use
ASGI when a platform expects an ASGI callable. Use WSGI only for compatibility
with older hosting stacks.

```bash
uv run quater dev main.py --interface rsgi
uv run quater dev main.py --interface asgi
uv run quater dev main.py --interface wsgi
```

Quater rejects WebSocket scopes today. It has no framework-level WebSocket API
in this release.

## What Can Go Wrong

`--app is required unless QUATER_APP is set`
: Set `QUATER_APP=main:app`, pass `--app main:app`, or use `quater dev main.py`
  for server startup.

`MCP tools require mcp_auth`
: Add `mcp_auth=authenticate` before declaring a route with `tool=True`.

`CLI actions require cli_auth`
: Add `cli_auth=authenticate` before declaring a route with `cli=True`.

`Missing required query parameter: page`
: Send the query parameter or give the handler parameter a default.

`Malformed JSON body`
: Send valid JSON and set `content-type: application/json` when you call the
  route manually.

`Unsupported form content type`
: Send form requests as `application/x-www-form-urlencoded` or
  `multipart/form-data`.

## Also See

- [Why Quater Exists](/en/latest/why-quater): understand the backend model behind
  this example.
- [Routes and Handlers](/en/latest/routes-handlers): learn route binding and
  handler rules.
- [Actions and CLI](/en/latest/actions): use dry-run, approval, remotes, and
  machine-readable output.
- [MCP](/en/latest/mcp): understand `mcp_auth`, tool schemas, and MCP errors.
- [Testing](/en/latest/testing): test this app without opening a port.
