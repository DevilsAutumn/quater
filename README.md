# Quater

Most backend frameworks were designed for one main job: serve data to a
frontend, then let humans click through that frontend to get work done.

That model still matters, but it is no longer enough. Moving ahead, more work is going to be
done by AI agents. Asking those agents to use a product through screens, buttons,
and forms is slow, fragile, and often the wrong level of access. Agents need a
safe way to work with the backend directly.

That does not mean giving agents unlimited access. It means exposing the right
operations, with clear inputs, clear descriptions, real auth, audit trails, and
approval gates where the action is sensitive.

Quater is a Python backend framework built for this shift. You build a normal
backend for people and services, and you can expose selected operations directly
to MCP Clients through MCP or to AI agents through the CLI. The same operation can
serve the app, power an agent, and support production workflows without becoming
three different pieces of code.

The goal is simple: make the backend usable by humans and operable by AI agents,
without losing safety, structure, or ownership of the application logic.

Quater is not trying to replace Django/FastAPI/Flask, ship an ORM, or hide your architecture
behind a large dependency graph. It focuses on the parts this new backend model
needs: typed handlers, explicit auth boundaries, AI-readable metadata,
operator-friendly actions, generated docs, and a small request path.

```mermaid
flowchart TB
    caller["Caller\nperson, service, or AI agent"]
    http["HTTP request\nGET /orders/ord_1001"]
    mcp["MCP tool call\ntools/call get_order"]
    remote_cli["Remote CLI action\nquater call store get_order"]
    adapter["Server adapter\nRSGI / ASGI / WSGI"]
    checks["Framework checks\nhost, body limit, CORS, request id"]
    router["Route metadata\nmethod, path, auth, resources"]
    surface_auth["Surface auth\nmcp_auth or cli_auth"]
    route_auth["Route auth\nauth="]
    handler["Your handler\nget_order(...)"]
    response["Serialized response\nJSON, text, bytes, stream"]

    caller --> http
    caller --> mcp
    caller --> remote_cli
    http --> adapter
    mcp --> adapter
    remote_cli --> adapter
    adapter --> checks
    checks --> router
    router --> surface_auth
    router --> route_auth
    surface_auth --> route_auth
    route_auth --> handler
    handler --> response
```

## A Small App

```python
from quater import AuthContext, AuthRequest, HTTPError, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer admin-token":
        return None
    return AuthContext(subject="admin")


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
    return {
        **order,
        "subject": request.auth.subject,
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
    }
```

Run it:

```bash
uv add quater
quater dev main.py
```

Expected server output:

```text
[INFO] Starting granian
[INFO] Listening at: http://127.0.0.1:8000
```

Call HTTP:

```bash
curl -H "Authorization: Bearer admin-token" \
  http://127.0.0.1:8000/orders/ord_1001
```

```json
{
  "id": "ord_1001",
  "status": "paid",
  "total": 42.5,
  "subject": "admin",
  "source": "api",
  "entrypoint": "server"
}
```

Call the same handler from the local CLI without a server round trip:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=admin-token
quater actions list
quater call get_order --order-id ord_1001
```

```json
{
  "id": "ord_1001",
  "status": "paid",
  "total": 42.5,
  "subject": "admin",
  "source": "cli",
  "entrypoint": "local"
}
```

For a hosted app, connect once and call the named remote:

```bash
quater connect store https://api.example.com --token admin-token
quater actions describe store get_order
quater call store get_order --order-id ord_1001
```

## Why This Shape

Quater treats HTTP, MCP, and CLI as different ways to reach the same backend
capability, not as three products you have to maintain.

- **For people and services:** Quater gives you normal HTTP APIs with route
  decorators, OpenAPI, Swagger UI, request binding, response classes, route
  groups, middleware, and tests.
- **For MCP Clients:** `tool=True` exposes selected routes through MCP with
  required descriptions, generated input schemas, transport auth, MCP docs, and
  audit hooks.
- **For AI agents:** `cli=True` exposes selected routes as local or remote CLI
  actions with discovery, dry-run, approval hooks, and JSON output for scripts.
- **For the app itself:** route auth, resources, `app.state`, lifespan hooks,
  and serialization stay attached to the handler instead of drifting into
  wrappers.
- **For performance:** the request path stays deliberately small with
  Granian/RSGI, msgspec JSON, and a native route matcher.

## Current Status

Quater is pre-release. The documented top-level imports are the public surface,
but names and defaults can still change before the first stable release. Pin the
version you test with.

## Documentation

- [Quickstart](docs/en/latest/quickstart.md): build the first app.
- [Why Quater Exists](docs/en/latest/why-quater.md): understand the problem
  Quater is built around.
- [Manual](docs/en/latest/index.md): read the full guide and reference.

## Working On Quater

This repo uses [uv](https://docs.astral.sh/uv/) for local development:

```bash
uv sync --group dev
uv run pytest
uv run mypy
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv build
```

Docs use VitePress:

```bash
npm install
npm run docs:reference
npm run docs:dev
npm run docs:build
```
