# HTTP, MCP, And CLI Surfaces

This page explains how one Quater route can be reached through HTTP, MCP, and
CLI without turning into three implementations.

## Prerequisites

Read [Why Quater Exists](/en/latest/why-quater) and
[Routes and Handlers](/en/latest/routes-handlers).

## The Model

HTTP is the default surface. If you declare `@app.get(...)`, you have an HTTP
route.

MCP and CLI are opt-in:

- `tool=True` exposes the route as an MCP tool for MCP Clients.
- `cli=True` exposes the route as a CLI action for AI agents.

The surfaces do not share transport auth. They converge after the surface is
accepted and Quater resolves the call to the route.

```mermaid
flowchart TB
    caller["caller\nperson, service, or AI agent"]
    http["HTTP API\nnormal request"]
    mcp["MCP tool\nagent call"]
    cli["CLI action\nlocal or remote"]
    surface_auth["surface auth\nmcp_auth or cli_auth"]
    route["route\nmetadata and route auth"]
    handler["handler\nyour code"]

    caller --> http --> route
    caller --> mcp --> surface_auth --> route
    caller --> cli --> surface_auth
    surface_auth --> route --> handler
```

## One Route, Three Access Paths

```python
from quater import AuthContext, AuthRequest, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="cust_123")


app = Quater(mcp_auth=authenticate, cli_auth=authenticate)


@app.get(
    "/orders/{order_id}",
    tool=True,
    cli=True,
    auth=authenticate,
    description="Fetch one order by id.",
)
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {
        "order_id": order_id,
        "subject": request.auth.subject,
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
    }
```

HTTP output:

```json
{
  "order_id": "ord_1001",
  "subject": "cust_123",
  "source": "api",
  "entrypoint": "server"
}
```

Local CLI output:

```json
{
  "order_id": "ord_1001",
  "subject": "cust_123",
  "source": "cli",
  "entrypoint": "local"
}
```

MCP returns the same handler result inside a JSON-RPC tool response.

## When To Use Each Surface

Use HTTP for the product API and service-to-service calls.

Use MCP when an AI agent should discover and call a backend operation with a
structured schema.

Use CLI when an operator or script should run a backend operation locally or
against a hosted app.

## What Can Go Wrong

`MCP tools require mcp_auth`
: Add `mcp_auth=...` before declaring any `tool=True` route.

`CLI actions require cli_auth`
: Add `cli_auth=...` before declaring any `cli=True` route.

`needs_approval requires tool=True or cli=True`
: Approval only applies to operations exposed outside normal HTTP.

## Also See

- [MCP Tools](/en/latest/mcp): agent-facing tool details.
- [Actions and CLI](/en/latest/actions): local and remote action details.
- [Auth Model](/en/latest/auth-model): exact auth order across surfaces.
