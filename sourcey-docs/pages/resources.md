---
description: Reference for Resource, Quater's scoped dependency-injection primitive for app-owned values.
---

# Resources Reference

This page documents `Resource`, the scoped injection primitive.

## Prerequisites

Read [Resources and Injection](/en/dev/resources). Use `Resource` for
app-owned values that should not come from HTTP, MCP, or CLI arguments.

```python
from quater import Resource
```

## Resource {#symbol-resource}

Added in `0.1.0a1`.

```python
Resource(
    provider: ResourceProvider[T],
    scope: ResourceScope = "request",
    name: str | None = None,
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `provider` | `ResourceProvider[T]` | required | Callable that creates the value. |
| `scope` | `ResourceScope` | `"request"` | Lifetime: `"request"` or `"function"`. |
| `name` | `str \| None` | `None` | Name used in resource error messages. |

Returns: `None`. Bind the instance to a handler parameter either through a route
`inject={...}` map or in the parameter's `Annotated[...]` type metadata.

Example:

```python
from collections.abc import AsyncIterator

from quater import Quater, Request, Resource

app = Quater()


async def session_provider(request: Request) -> AsyncIterator[str]:
    yield "db-session"


db_session = Resource(session_provider, name="db_session")


@app.get("/orders/{order_id}", inject={"session": db_session})
async def get_order(order_id: str, session: str) -> dict[str, str]:
    return {"order_id": order_id, "session": session}
```

Expected response:

```json
{
  "order_id": "ord_1001",
  "session": "db-session"
}
```

Equivalently, carry the resource in the parameter's `Annotated[...]` metadata,
which also lets you reuse one alias across handlers:

```python
from typing import Annotated

SessionDep = Annotated[str, db_session]


@app.get("/orders/{order_id}")
async def get_order(order_id: str, session: SessionDep) -> dict[str, str]:
    return {"order_id": order_id, "session": session}
```

A parameter may name a resource in `inject` or in its annotation, but not both,
and a `Resource` cannot be used as a parameter default. See
[Two ways to wire a resource](/en/dev/resources#two-ways-to-wire-a-resource).

## Provider Forms

A provider may accept no parameters or one `Request` parameter. It may return a
value, awaitable, context manager, async context manager, generator, or async
generator.

Generators must yield exactly once. Request-scoped resources close after the
response path finishes. Function-scoped resources close before after-response
middleware runs, so cleanup failures can still become the request's response.

## Methods And Properties

| Member | Return | Description |
| --- | --- | --- |
| `display_name` | `str` | `name`, provider `__name__`, or `"resource"`. |
| `resolve(request, stack)` | `T` | Resolves the resource into the stack you provide. Application code usually does not call this directly. |

The low-level `resolve(request, stack)` helper uses the caller's stack; it does
not create separate function/request teardown boundaries.

## What Can Go Wrong

`Resource scope must be 'function' or 'request'`
: Use `"request"` for resources that must stay alive through streaming, or
  `"function"` for resources that must finish before the response is sent.

`Resource provider must be callable`
: Pass a function or callable object.

`Resource providers cannot use *args or **kwargs`
: Give the provider a concrete signature.

`Resource providers may accept only one parameter: request`
: Use zero parameters or one request parameter.

`Resource provider parameter must be named 'request' or typed as Request`
: Rename or annotate the parameter.

`Resource provider 'db_session' yielded more than once`
: Yield one value, then cleanup after it.

`Injected parameter 'session' is declared both in inject= and in its type annotation`
: A parameter names the same resource in `inject` and in its `Annotated[...]`
  metadata. Keep one.

`Resource for 'session' must be declared in inject= or in the type annotation (Annotated[T, resource]), not as a default value`
: A `Resource` was used as a parameter default. Move it to `inject` or the
  annotation.

`Only one resource is supported in a type annotation`
: A parameter's `Annotated[...]` metadata lists more than one `Resource`.

`Request-scoped resource 'current_user' cannot depend on function-scoped resource 'session'`
: A longer-lived resource cannot depend on a shorter-lived one. Make both
  resources request-scoped, or make the dependent resource function-scoped too.

## Also See

- [Resources and Injection](/en/dev/resources): full lifecycle and examples.
- [Reference: Application](./application#symbol-quater): `inject` route option.
- [Testing](/en/dev/testing#resources): testing resource cleanup.
