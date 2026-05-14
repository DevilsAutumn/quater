# Resources And Injection

This page explains `app.state` and request-scoped `Resource` injection.

## Prerequisites

Read [Quickstart](/en/latest/quickstart) and [Public API](/en/latest/api). You
should know async context managers if you plan to inject database sessions.

## Why This Exists

Real handlers need values that should never come from the client: database
sessions, cache clients, tenant objects, feature flags, and API clients.

Quater keeps those values explicit:

- Long-lived objects live on `app.state`.
- Per-request values use `Resource`.
- Routes opt in with `inject={...}`.

Quater does not build a hidden dependency graph. A reader can inspect the route
decorator and know which handler parameters come from the app.

## Resource Lifecycle

```mermaid
flowchart TB
    startup["your code: on_startup\ncreate long-lived pool"]
    state["framework: app.state\nholds pool/client/config"]
    request["framework: request starts"]
    provider["your code: Resource provider\ncreates request value"]
    handler["your code: handler\nreceives injected value"]
    response["framework: response created"]
    cleanup["framework: cleanup after response\nalso on errors"]
    shutdown["your code: on_shutdown\nclose long-lived pool"]

    startup --> state
    state --> request --> provider --> handler --> response --> cleanup
    state --> shutdown
```

Cleanup runs after response creation. For streaming responses, Quater keeps the
resource alive until the response body has been consumed by the adapter.

## A Runnable Example

```python
from collections.abc import AsyncIterator

from quater import Quater, Request, Resource


class OrderStore:
    async def get_order(self, order_id: str) -> dict[str, object]:
        return {"id": order_id, "status": "paid"}

    async def close(self) -> None:
        pass


app = Quater()


@app.on_startup
async def startup() -> None:
    app.state.store = OrderStore()


@app.on_shutdown
async def shutdown() -> None:
    await app.state.store.close()


async def store_resource(request: Request) -> AsyncIterator[OrderStore]:
    yield request.app.state.store


store = Resource(store_resource, name="store")


@app.get("/orders/{order_id}", inject={"store": store})
async def get_order(order_id: str, store: OrderStore) -> dict[str, object]:
    return await store.get_order(order_id)
```

Expected response:

```json
{
  "id": "ord_1001",
  "status": "paid"
}
```

## Provider Forms

A provider can accept no arguments:

```python
async def settings_resource() -> dict[str, str]:
    return {"region": "us-east-1"}
```

Or it can accept the current `Request`:

```python
async def tenant_resource(request: Request) -> str:
    return request.headers.get("x-tenant-id", "public")
```

It can return:

- a plain value
- an awaitable value
- a sync context manager
- an async context manager
- a sync generator that yields once
- an async generator that yields once

Database sessions usually use an async generator:

```python
from collections.abc import AsyncIterator

from quater import Request


async def session_resource(request: Request) -> AsyncIterator[DatabaseSession]:
    async with request.app.state.database.session() as session:
        yield session
```

## Route Usage

```python
db_session = Resource(session_resource, name="db_session")


@app.post("/orders", inject={"session": db_session})
async def create_order(order: CreateOrder, session: DatabaseSession) -> dict[str, str]:
    created = await session.create_order(order)
    return {"id": created.id}
```

The injected `session` does not appear in:

- OpenAPI request parameters
- MCP input schemas
- CLI action schemas
- HTTP path, query, header, cookie, or body binding

That keeps app-owned objects away from untrusted caller input.

## Groups

Use a [`RouteGroup`](/en/latest/reference/application#symbol-routegroup) when
several routes in one feature need the same resource:

```python
from quater import Quater, Resource, RouteGroup

app = Quater()
orders = RouteGroup(prefix="/orders", inject={"session": db_session})


@orders.get("/{order_id}")
async def get_order(order_id: str, session: DatabaseSession) -> dict[str, object]:
    order = await session.fetch_order(order_id)
    return {"id": order.id}


app.include(orders)
```

Quater flattens group resources into the final route when the group is included.
It does not resolve resources during route matching.

## MCP And CLI

Resources work the same through HTTP, MCP, local CLI, and remote CLI:

```python
@app.get(
    "/orders/{order_id}",
    tool=True,
    cli=True,
    inject={"session": db_session},
    description="Fetch one order.",
)
async def get_order(order_id: str, session: DatabaseSession) -> dict[str, object]:
    order = await session.fetch_order(order_id)
    return {"id": order.id, "status": order.status}
```

The generated MCP and CLI schemas include `order_id`, not `session`.

## What Can Go Wrong

`Injected parameter 'session' does not exist on the handler`
: The `inject` key must match a handler parameter name.

`Injected parameter 'session' cannot use a parameter marker`
: Do not combine `Resource` injection with `Path`, `Query`, `Body`, `Header`, or
  `Cookie`.

`Resource provider parameter must be named 'request' or typed as Request`
: Rename the provider argument to `request` or annotate it as `Request`.

`Resource providers cannot use *args or **kwargs`
: Give the provider either zero parameters or one request parameter.

`Resource provider 'db_session' did not yield a value`
: A generator provider must yield exactly one value.

`Resource provider 'db_session' yielded more than once`
: Use one `yield`, then cleanup after it.

`Duplicate injected parameter: session`
: A group and a route both define `session` with different `Resource` objects.
  Use the same object or rename one parameter.

## Also See

- [Public API](/en/latest/api): see `app.state`, lifespan hooks, and `inject`.
- [Testing](/en/latest/testing): test resource cleanup through `TestClient`.
- [Reference: Resources](/en/latest/reference/resources): inspect the exact
  `Resource` signature.
- [Deployment](/en/latest/deployment): understand how workers affect app state.
