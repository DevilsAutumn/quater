---
description: Reference for Quater request binding markers, Path, Query, Body, Form, File, Header, and Cookie.
---

# Parameter Reference

This page documents request binding markers: `Path`, `Query`, `Body`, `Form`,
`File`, `Header`, and `Cookie`.

## Prerequisites

Read [Public API](/en/dev/api#binding). Markers are needed when inference is
not enough, or when you want aliases and schema descriptions.

```python
from quater import Body, Cookie, File, Form, Header, Path, Query
```

Markers can be used as defaults or inside `typing.Annotated`.
`Query`, `Header`, `Cookie`, and `Form` bind scalar values only: `str`, `int`,
`float`, or `bool`. Use `Body` for structured JSON input and `File` for
multipart file uploads.

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

`Body` follows normal Python default rules. If an HTTP request has no body
bytes, Quater treats the body as missing input: a required body returns
`400 Missing required body parameter`, a body with a default uses that default,
and a `T | None` body receives `None`.

This only applies to an empty body. A non-empty body must still be valid JSON,
so `{"broken"` returns `400 Malformed JSON body` even when the parameter has a
default. JSON `null` is also real input, not a missing body. For typed bodies,
use `T | None` when `null` should be accepted.

## Form {#symbol-form}

Added in `0.1.0a1`.

```python
Form(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Omit to require the form field. |
| `alias` | `str \| None` | `None` | Form field name. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |

`Form` reads `application/x-www-form-urlencoded` and `multipart/form-data`
fields. It is for scalar values such as login forms, OAuth-style token requests,
and compatibility with clients that do not send JSON.

## File {#symbol-file}

Added in `0.1.0a1`.

```python
File(
    default: object = ...,
    *,
    alias: str | None = None,
    description: str | None = None,
) -> Any
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `default` | `object` | `...` | Omit to require the file. |
| `alias` | `str \| None` | `None` | Multipart field name. |
| `description` | `str \| None` | `None` | Schema description. Empty strings become `None`. |

`File` reads `multipart/form-data` file parts. Handler annotations may be
[`UploadFile`](./request#symbol-uploadfile), `bytes`, `list[UploadFile]`, or
`list[bytes]`. Quater keeps file uploads HTTP-only in this release; routes with
`File` parameters cannot be exposed as MCP tools or CLI actions.

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

Form and file uploads use explicit markers too:

```python
from quater import File, Form, Quater, UploadFile

app = Quater()


@app.post("/imports")
async def import_document(
    account_id: str = Form(description="Account id."),
    document: UploadFile = File(description="CSV document."),
) -> dict[str, object]:
    content = await document.read()
    return {
        "account_id": account_id,
        "filename": document.filename,
        "size": len(content),
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

`Form parameter 'profile' must use str, int, float, or bool`
: Use `File` for uploaded files and `Body` for structured JSON.

`File parameter 'document' must use UploadFile, bytes, list[UploadFile], or list[bytes]`
: Change the handler annotation to one of the supported file shapes.

`JSON body parameters cannot be combined with form or file parameters`
: A request body is either JSON or form data. Split the route or move all input
  to one format.

## Also See

- [Public API](/en/dev/api#binding): binding order and mental model.
- [Actions and CLI](/en/dev/actions#argument-binding): marker behavior in CLI.
- [MCP](/en/dev/mcp#tool-schemas): marker behavior in tool schemas.
