# Resources and Injection

Most real apps need objects that are not part of the HTTP request:
database sessions, cache clients, tenant loaders, feature flags, SDK clients,
or small request-scoped services.

In Quater, those values are injected with [`Resource`](./reference/resources#symbol-resource).
The route stays explicit: you name the handler parameter that should receive
the resource, and Quater resolves it for that handler call.

```python
from collections.abc import AsyncIterator

from quater import Quater, Request, Resource

app = Quater()


async def session_resource(request: Request) -> AsyncIterator[DatabaseSession]:
    async with request.app.state.database.session() as session:
        yield session


db_session = Resource(session_resource, name="db_session")


@app.get("/orders/{order_id}", inject={"session": db_session})
async def get_order(order_id: str, session: DatabaseSession) -> dict[str, object]:
    order = await session.fetch_order(order_id)
    return {"id": order.id, "status": order.status}
```

The handler signature is still normal Python. `session` is not read from the
path, query string, body, headers, cookies, MCP arguments, or CLI arguments.
It is created inside the framework for the current call.

## Why Quater Uses Resource

Quater does not try to build a large hidden dependency graph. That can become
hard to debug once an app grows.

Instead, injection has three simple rules:

- Long-lived objects belong on [`app.state`](./reference/request#symbol-state).
- Per-request objects are declared as [`Resource`](./reference/resources#symbol-resource).
- A route opts into resources with `inject={...}`.

This keeps lifetimes visible. A developer reading the route can see which
parameters come from the client and which ones come from the app.

## Provider Shapes

A provider can accept no arguments:

```python
async def settings_resource() -> Settings:
    return Settings.from_env()
```

Or it can accept the current [`Request`](./reference/request#symbol-request):

```python
async def tenant_resource(request: Request) -> Tenant:
    tenant_id = request.headers.get("x-tenant-id")
    return await request.app.state.tenants.load(tenant_id)
```

Providers can return a value directly, return an awaitable, return a context
manager, return an async context manager, or yield one value:

```python
async def session_resource(request: Request) -> AsyncIterator[DatabaseSession]:
    async with request.app.state.database.session() as session:
        yield session
```

When a provider yields or returns a context manager, Quater closes it after the
handler finishes. Cleanup also runs when the handler raises.

::: tip
Use `app.state` for the database pool or engine, and use a request
`Resource` for the database session. That gives you one shared pool and one
short-lived session per request.
:::

## Route Usage

Use `inject` on the route decorator:

```python
@app.post("/orders", inject={"session": db_session})
async def create_order(order: CreateOrder, session: DatabaseSession) -> dict[str, str]:
    created = await session.create_order(order)
    return {"id": created.id}
```

The key in `inject` must match a handler parameter name. If it does not, Quater
fails while routes compile.

Injected parameters cannot also be path, query, header, cookie, or body
parameters. This is intentional: client input and app-owned resources should
not compete for the same name.

## Groups

[`RouteGroup`](./reference/application#symbol-routegroup) can share resources
across a feature area:

```python
from quater import RouteGroup

orders = RouteGroup(prefix="/orders", inject={"session": db_session})


@orders.get("/{order_id}")
async def get_order(order_id: str, session: DatabaseSession) -> dict[str, object]:
    order = await session.fetch_order(order_id)
    return {"id": order.id}


app.include(orders)
```

If a parent group and a child route define the same injected parameter with
different resources, Quater raises a configuration error. That avoids a quiet
override that only shows up in production.

## MCP and CLI

Resources work the same way for HTTP, MCP tools, and CLI actions.

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

The generated MCP input schema and CLI action schema include `order_id`, but
not `session`. A remote caller cannot pass a fake session value.

## Validation

Quater fails route compilation when:

- `inject` points to a parameter that does not exist.
- An injected parameter uses `Path`, `Query`, `Body`, `Header`, or `Cookie`.
- An injected parameter also appears in the route path.
- A provider accepts more than one argument.
- A provider argument is not named `request` and is not typed as `Request`.

These errors are raised early because a resource bug usually means the app was
configured incorrectly.
