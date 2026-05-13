# Quater

Quater is a typed Python backend framework for building APIs that humans use
directly and AI agents can operate safely.

As AI systems become another real caller of backend systems, backends are no longer
called from one place. The same business operation may be used by a browser, an
internal service, an MCP client, or an operator running a CLI command. In
existing frameworks, those access paths become separate code paths: an HTTP
endpoint, an AI tool wrapper, an admin script, and extra glue code between them.

Quater is built around one rule: declare the operation once, then choose which
surfaces may call it.

You write one handler. It can remain a normal HTTP endpoint, and when you opt
in, Quater derives an MCP tool or CLI action from that route metadata. HTTP,
MCP, and CLI still have separate runtime surfaces, but they call the same
handler instead of asking you to maintain separate tool code or admin scripts.
Parameter binding, route-level auth, response normalization, and generated
schemas stay tied to the route.

Request flow:

<img width="1400" height="1524" alt="diagram" src="https://github.com/user-attachments/assets/e229e10d-6883-4601-ba4e-100a24e6ed19" />


## What Quater Focuses On

- **One declared operation:** HTTP, MCP tools, and CLI actions can share the same
  handler.
- **AI-readable operations:** descriptions and generated schemas tell agents
  what an exposed operation does and how to call it.
- **Explicit auth boundaries:** normal routes use `auth=...`, MCP uses
  `mcp_auth`, and CLI actions use `cli_auth`.
- **Operational safety:** CLI actions support dry-run and approval hooks for
  sensitive workflows.
- **Generated docs:** OpenAPI, Swagger UI, and MCP tool docs are generated from
  route metadata.
- **Fast defaults:** Quater uses Granian/RSGI, msgspec JSON, and a native route
  matcher.

## A Small App

```python
from quater import AuthContext, AuthRequest, HTTPError, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer admin-token":
        return None
    return AuthContext(subject="admin")


app = Quater(
    mcp_auth=authenticate,
    cli_auth=authenticate,
)
ORDER_STORE: dict[str, dict[str, object]] = {
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
    assert request.auth is not None
    order = ORDER_STORE.get(order_id)
    if order is None:
        raise HTTPError("Order not found", status_code=404)
    return {
        **order,
        "requested_by": request.auth.subject,
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
    }
```

Run it:

```bash
quater dev main.py
```

This is one small app, but it already shows the main idea:

- `GET /health` is a plain HTTP route.
- `GET /orders/ord_1001` is still a normal HTTP route.
- Because `get_order` has `tool=True`, it is also available through MCP.
- Because `get_order` has `cli=True`, it is also available as a CLI action.
- The same `auth=authenticate` hook protects the handler no matter which
  surface calls it.

Quater serves docs by default:

- `GET /docs` for Swagger UI.
- `GET /openapi.json` for OpenAPI.
- `GET /mcp/docs` for exposed MCP tools.

For AI clients, the useful part is not just that `get_order` becomes a tool. The
operation has a human-written description and a generated input schema, so the
model can understand when to call it and what arguments are valid.

CLI discovery is intentionally compact:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=admin-token
quater actions list
```

```text
get_order
  Fetch one order by id.
```

The detailed command help lives behind `describe`:

```bash
quater actions describe get_order
```

And execution stays straightforward:

```bash
quater call get_order --order-id ord_1001
```

If you do not want to set environment variables, pass them inline:

```bash
quater --app main:app --token admin-token actions list
```

For a hosted app, connect once and call the named remote after that:

```bash
quater connect store https://api.example.com --token admin-token
quater actions list store
quater call store get_order --order-id ord_1001
```

Dry-run shows how Quater will call the route before the handler runs:

```text
Dry run OK: get_order
  GET /orders/{order_id}
  arguments hash: sha256:...
  protected action: no
  approval token: not required
```

## Current Status

Quater is in its first alpha. The core is intentionally small: typed handlers,
RSGI-first serving, generated docs, MCP tools, CLI actions, explicit auth, and
security defaults. The public import boundary is documented, but the API is
still pre-release, so some names may change before the first stable version.

## Read Next

- [Quickstart](docs/en/latest/quickstart.md)
- [Actions and CLI](docs/en/latest/actions.md)
- [Deployment](docs/en/latest/deployment.md)
- [MCP](docs/en/latest/mcp.md)
- [Security](docs/en/latest/security.md)
- [Public API](docs/en/latest/api.md)
- [Stability](docs/en/latest/stability.md)
- [Reference](docs/en/latest/reference/index.md)

## Working On Quater

This repo uses `uv`.

```bash
uv sync --group dev
uv run pytest
uv run mypy src examples tests
uv run ruff check .
uv build
```

Docs use VitePress:

```bash
npm install
npm run docs:reference
npm run docs:dev
npm run docs:build
```
