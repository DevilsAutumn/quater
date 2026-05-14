# Parameter Reference

This page documents request binding markers: `Path`, `Query`, `Body`, `Header`,
and `Cookie`.

## Prerequisites

Read [Public API](/en/latest/api#binding). Markers are needed when inference is
not enough, or when you want aliases and schema descriptions.

```python
from quater import Body, Cookie, Header, Path, Query
```

Markers can be used as defaults or inside `typing.Annotated`.

```python
from typing import Annotated

from quater import Query


async def search(
    q: str = Query(description="Search text"),
    page: Annotated[int, Query(alias="p")] = 1,
) -> dict[str, object]:
    return {"q": q, "page": page}
```

## Path {#symbol-path}

Added in `0.1.0a1`.

```python
Path(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Path parameters are required. Leave unset. |
| `alias` | `str \| None` | `None` | Route variable name when it differs from the Python name. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |

## Query {#symbol-query}

Added in `0.1.0a1`.

```python
Query(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Omit to require the query parameter. |
| `alias` | `str \| None` | `None` | Query-string name. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |

## Body {#symbol-body}

Added in `0.1.0a1`.

```python
Body(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Omit to require the body parameter. |
| `alias` | `str \| None` | `None` | MCP and CLI argument name for the body. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |

## Header {#symbol-header}

Added in `0.1.0a1`.

```python
Header(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
    convert_underscores: bool = True,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Omit to require the header. |
| `alias` | `str \| None` | `None` | HTTP header name. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |
| `convert_underscores` | `bool` | `True` | Converts `user_agent` to `user-agent` when no alias exists. |

## Cookie {#symbol-cookie}

Added in `0.1.0a1`.

```python
Cookie(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Omit to require the cookie. |
| `alias` | `str \| None` | `None` | Cookie name. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |

## Complete Example

```python
import msgspec

from quater import Body, Header, Path, Query, Quater


class UpdateOrder(msgspec.Struct):
    status: str


app = Quater()


@app.patch("/orders/{id}")
async def update_order(
    order_id: str = Path(alias="id"),
    payload: UpdateOrder = Body(description="New order state."),
    include_events: bool = Query(default=False, alias="include-events"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "status": payload.status,
        "include_events": include_events,
        "request_id": request_id,
    }
```

Expected body:

```json
{
  "payload": {
    "status": "shipped"
  }
}
```

## What Can Go Wrong

`Parameter alias must not be empty`
: Give `alias` a non-empty string or omit it.

`Parameter alias must not contain control characters`
: Remove control characters from aliases.

`Only one parameter marker is supported`
: Do not put two markers in one `Annotated` type.

`Parameter 'page' cannot define a default twice`
: Put the default in the marker or in the Python signature, not both.

`Query parameter 'filters' must use str, int, float, or bool`
: Use `Body` for structured data.

## Also See

- [Public API](/en/latest/api#binding): binding order and mental model.
- [Actions and CLI](/en/latest/actions#argument-binding): marker behavior in CLI.
- [MCP](/en/latest/mcp#tool-schemas): marker behavior in tool schemas.
