# Resources Reference

This page documents `Resource`, the request-scoped injection primitive.

## Prerequisites

Read [Resources and Injection](/en/latest/resources). Use `Resource` for
app-owned values that should not come from HTTP, MCP, or CLI arguments.

```python
from quater import Resource
```

## Resource {#symbol-resource}

Added in `0.1.0a1`.

```python
Resource(
    provider: ResourceProvider,
    scope: ResourceScope = "request",
    name: str | None = None,
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `provider` | `ResourceProvider` | required | Callable that creates the value. |
| `scope` | `ResourceScope` | `"request"` | Lifetime. Only `"request"` exists today. |
| `name` | `str \| None` | `None` | Name used in resource error messages. |

Returns: `None`. Use the instance in a route `inject={...}` map.

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

## Provider Forms

A provider may accept no parameters or one `Request` parameter. It may return a
value, awaitable, context manager, async context manager, generator, or async
generator.

Generators must yield exactly once. Quater closes them after the response path
finishes.

## Methods And Properties

| Member | Return | Description |
| --- | --- | --- |
| `display_name` | `str` | `name`, provider `__name__`, or `"resource"`. |
| `resolve(request, stack)` | `object` | Resolves the resource for one handler call. Application code usually does not call this directly. |

## What Can Go Wrong

`Resource scope must be 'request'`
: Use the only supported scope.

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

## Also See

- [Resources and Injection](/en/latest/resources): full lifecycle and examples.
- [Reference: Application](./application#symbol-quater): `inject` route option.
- [Testing](/en/latest/testing#resources): testing resource cleanup.
