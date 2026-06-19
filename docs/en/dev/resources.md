---
title: Resources and injection in Quater
description: Use Quater app.state and Resource providers for long-lived application objects and per-request dependencies.
---

# Resources And Injection

This page explains `app.state` and scoped `Resource` injection.

## Prerequisites

Read [Quickstart](/en/dev/quickstart) and [Public API](/en/dev/api). You
should know async context managers if you plan to inject database sessions.

## Why This Exists

Real handlers need values that should never come from the client: database
sessions, cache clients, tenant objects, feature flags, and API clients.

Quater keeps those values explicit:

- Long-lived objects live on `app.state`.
- Per-request values use `Resource`.
- Routes opt in by naming the `Resource`, either in the decorator's
  `inject={...}` map or in the parameter's type annotation.

Quater does not build a hidden dependency graph. A reader can see every injected
parameter at the route — in the decorator's `inject` map or in the handler
signature — and know which values come from the app.

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

Cleanup timing depends on the resource scope. Request-scoped resources close
after the response path finishes; for streaming responses, Quater keeps them
alive until the response body has been consumed by the adapter.
Function-scoped resources close before the response leaves the route pipeline.
On route and action paths, that happens before after-response middleware runs.

### Resource lifetimes

Every request gets shared resource scopes: places that open the values it
needs, cache them, and clean them up. Two things follow from that.

First, the same `Resource` resolves once per request within its lifetime. If two
parameters — or auth and, later, the handler — ask for the same `Resource`
object, they get the same instance. A `Resource` that opens a database session
opens **one** session per request, not one per parameter.

Second, the scopes are strictly per request. Nothing opened for one request is
ever visible to another, and when the request finishes, every resource it
opened is torn down once, in the reverse of the order it was opened. If a later
resource fails to open, the ones already open are still cleaned up.

The scopes are lazy: a request whose handler injects nothing never creates one.

Use the default `scope="request"` when the value must stay alive through
streaming. Use `scope="function"` for unit-of-work resources that commit in
their post-yield code and need commit failures to become a real error response.

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

`Resource` is generic: `Resource(session_resource)` carries the resolved value
type from the provider. That matters when app code resolves a resource manually,
usually inside authentication:

```python
db_session = Resource(session_resource)


async def authenticate(request: Request):
    token = request.headers.get("authorization")
    if token is None:
        raise HTTPError("Unauthorized", status_code=401)
    session = await request.resolve(db_session)
    return await authenticate_token(session, token)
```

Use `await request.resolve(resource)` for the typed no-cast path. Handler
parameters should still use `inject={...}` or `Annotated[T, resource]`. Passing
an `Annotated` alias to `request.resolve()` is accepted for compatibility, but
the raw `Resource[T]` is the form type checkers can follow precisely.

## Resources That Depend On Resources

A provider can ask for other resources, the same way a handler does — with
`Annotated[T, resource]`. Quater resolves each dependency first, once in its
resource scope, and passes it in. The classic case is a current-user resource
that needs the database session to look the user up:

```python
from typing import Annotated

from quater import Request, Resource

db_session = Resource(session_resource, name="session")
SessionDep = Annotated[DatabaseSession, db_session]


async def current_user_provider(
    request: Request,
    session: SessionDep,
) -> User:
    user = await find_user(session, request.headers.get("authorization"))
    if user is None:
        raise UnauthorizedError
    return user


current_user = Resource(current_user_provider, name="current_user")
```

Because the session comes from the shared scope for that resource, the session
opened to look up the user is the *same* session a handler injects directly —
one connection for the whole request.

When the value is the *authenticated* user, prefer loading it once in the
authenticator and reading it back through `AuthContext.payload` instead of a
per-handler lookup resource. It shares the same request session and skips the
second query entirely. See
[Auth Model](./auth-model#reading-the-loaded-user-payload).

It stays explicit on purpose: a provider only receives a resource you point at
through its annotation. Nothing is guessed from a bare type. A provider
parameter that is neither named `request` nor annotated with a resource is
rejected when routes compile.

The dependency graph is checked at startup, not on the first request:

- A dependency cycle (a resource that needs itself, directly or through others)
  fails when routes compile.
- A provider parameter that can't be resolved fails when routes compile.

Dependencies are private to the provider: a resource and everything it depends
on stay out of OpenAPI, MCP, and CLI schemas. The session never shows up as a
tool input.

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

## Two Ways To Wire A Resource

A `Resource` is bound to a handler parameter by name. You can express that
binding in two places. Both produce the same binding, and both keep the
parameter out of every caller-facing schema.

### In the decorator (`inject={...}`)

The `inject` map keys each resource to a parameter name:

```python
@app.post("/orders", inject={"session": db_session})
async def create_order(order: CreateOrder, session: DatabaseSession) -> dict[str, str]:
    ...
```

The parameter (`session: DatabaseSession`) is a plain typed parameter; the
decorator says where its value comes from. This is the only form that a
[`RouteGroup`](#groups) can share across several routes, so prefer it when a
whole feature needs the same resource.

### In the type annotation (`Annotated[T, resource]`)

Put the `Resource` in the parameter's annotation. The parameter type is still
`T`; the resource rides along as annotation metadata that Quater reads at route
compilation:

```python
@app.post("/orders")
async def create_order(
    order: CreateOrder,
    session: Annotated[DatabaseSession, db_session],
) -> dict[str, str]:
    ...
```

This keeps the value and its provider next to the parameter, and it lets you
define a reusable alias once and share it across handlers — the same shape you
may know from other frameworks:

```python
from typing import Annotated

SessionDep = Annotated[DatabaseSession, db_session]


@app.get("/orders/{order_id}")
async def get_order(order_id: str, session: SessionDep) -> dict[str, str]:
    ...


@app.post("/orders")
async def create_order(order: CreateOrder, session: SessionDep) -> dict[str, str]:
    ...
```

Because the annotation type stays `DatabaseSession` and the parameter has no
default, this form type-checks cleanly under strict tools with no cast or
`# type: ignore`.

Define the `Resource` (and any `Annotated` alias) at module scope so Quater can
resolve the annotation when it compiles the route. If Quater needs a handler
parameter annotation to decide or validate where the value comes from, and that
annotation cannot be resolved, it rejects the route instead of guessing that the
parameter should come from caller input. The `inject={...}` form is explicit, so
its value type may still be local to an application factory. Malformed
annotations still fail during route compilation.

### Rules

- Declare a resource in **one** place per parameter. Naming the same parameter in
  both `inject={...}` and its annotation is rejected at route compilation.
- A `Resource` cannot go in a parameter's **default** value
  (`session: DatabaseSession = db_session`). Use `inject={...}` or the
  annotation instead; the default form is rejected with a clear error.

## Groups

Use a [`RouteGroup`](/en/dev/reference/application#symbol-routegroup) when
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

`Resource provider 'current_user' parameter 'mystery' could not be resolved: name it 'request' or annotate it with Annotated[T, resource]`
: A provider parameter is neither named `request` nor annotated with a resource.
  Name it `request`, annotate it `Annotated[T, some_resource]`, or remove it.

`Handler parameter 'session' on 'get_order' has annotation 'SessionDep' that could not be resolved`
: A handler parameter annotation refers to a type, `Resource`, or `Annotated`
  alias that is not resolvable from the handler's module. Move the referenced
  type or alias to module scope, import it in that module, or use `inject=`
  when the parameter is an app-owned resource value.

`Resource dependency cycle detected: a -> b -> a`
: A resource depends on itself, directly or through others. Break the loop.

`Resource provider parameter 'request' cannot be both the request and a resource`
: A parameter is named `request` and also annotated with a resource. Pick one.

`Resource providers may accept the request only once`
: A provider lists more than one request parameter. Keep a single one.

`Resource providers cannot use *args or **kwargs`
: Give the provider explicit parameters: `request` and/or resource dependencies.

`Resource provider 'db_session' did not yield a value`
: A generator provider must yield exactly one value.

`Resource provider 'db_session' yielded more than once`
: Use one `yield`, then cleanup after it.

`Duplicate injected parameter: session`
: A group and a route both define `session` with different `Resource` objects.
  Use the same object or rename one parameter.

`Injected parameter 'session' is declared both in inject= and in its type annotation`
: A parameter names the same resource in the decorator `inject` map and in its
  `Annotated[...]` metadata. Keep one.

`Resource for 'session' must be declared in inject= or in the type annotation (Annotated[T, resource]), not as a default value`
: A `Resource` was placed in a parameter's default value. Move it into the
  `inject` map or the parameter's annotation.

`Only one resource is supported in a type annotation`
: A parameter's `Annotated[...]` metadata lists more than one `Resource`. Use a
  single resource per parameter.

## Also See

- [Public API](/en/dev/api): see `app.state`, lifespan hooks, and `inject`.
- [Testing](/en/dev/testing): test resource cleanup through `TestClient`.
- [Reference: Resources](/en/dev/reference/resources): inspect the exact
  `Resource` signature.
- [Deployment](/en/dev/deployment): understand how workers affect app state.
