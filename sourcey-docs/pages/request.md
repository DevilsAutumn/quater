---
description: Reference for the Request object, State, and the request view objects available to Quater handlers.
---

# Request Reference

This page documents `Request`, `State`, and the request view objects available
from handlers.

## Prerequisites

Read [Public API](/en/dev/api#binding) for binding rules. Use `Request` when
you need headers, cookies, raw body access, auth, state, or call-source context.

```python
from quater import FormData, Request, State, UploadFile
```

## Request {#symbol-request}

Added in `0.1.0a1`.

Normalized request object used by HTTP, MCP, and CLI paths.

```python
Request(
    *,
    method: str,
    path: str,
    scheme: str = "http",
    headers: HeaderItems | Mapping[str, str] = (),
    query_string: str | bytes = "",
    body: RequestBody = None,
    auth: AuthContext | None = None,
    client: str | None = None,
    context: RequestContext | None = None,
    app: Quater | None = None,
    max_body_size: int | None = None,
    max_form_parts: int | None = None,
    max_form_field_size: int | None = None,
    max_file_size: int | None = None,
    upload_spool_size: int | None = None,
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | `str` | required | HTTP method. Quater stores it uppercase. |
| `path` | `str` | required | Path without query string. |
| `scheme` | `str` | `"http"` | Request scheme. Quater stores it lowercase. |
| `headers` | `HeaderItems \| Mapping[str, str]` | `()` | Incoming request headers. |
| `query_string` | `str \| bytes` | `""` | Raw query string. |
| `body` | `RequestBody` | `None` | Bytes, async body reader, or empty body. |
| `auth` | [`AuthContext`](./auth#symbol-authcontext) \| None | `None` | Initial auth context. Route auth usually sets it. |
| `client` | `str \| None` | `None` | Client address when available. |
| `context` | `RequestContext \| None` | `None` | Source and entrypoint metadata. |
| `app` | [`Quater`](./application#symbol-quater) \| None | `None` | App handling the request. Quater sets it at the app boundary. |
| `max_body_size` | `int \| None` | `None` | Per-request body size limit. |
| `max_form_parts` | `int \| None` | `None` | Per-request form field and file count limit. |
| `max_form_field_size` | `int \| None` | `None` | Per-request string form field size limit. |
| `max_file_size` | `int \| None` | `None` | Per-request uploaded file size limit. |
| `upload_spool_size` | `int \| None` | `None` | Per-request upload spool threshold. |

Normal app code receives a `Request`; it rarely constructs one directly outside
tests.

## Properties And Methods

| Member | Type | Description |
| --- | --- | --- |
| `method` | `str` | Uppercase method such as `GET`. |
| `path` | `str` | Request path without query string. |
| `scheme` | `str` | `http` or `https`. |
| `app` | [`Quater`](./application#symbol-quater) \| None | App instance once the request enters Quater. |
| `headers` | `Headers` | Case-insensitive header view. |
| `query` | `QueryParams` | Parsed query parameters. |
| `cookies` | `Cookies` | Cookies parsed from the `Cookie` header. |
| `auth` | [`AuthContext`](./auth#symbol-authcontext) \| None | Auth context returned by auth hooks. |
| `state` | [`State`](#symbol-state) | Request-local mutable state. |
| `context` | `RequestContext` | Source, entrypoint, request id, tool, and action metadata. |
| `client` | `str \| None` | Client address when available. |
| `body()` | `bytes` | Reads and caches the request body. |
| `json()` | `Any` | Parses and caches the JSON body with Quater's JSON decoder. |
| `form()` | [`FormData`](#symbol-formdata) | Parses and caches submitted form fields and files. |
| `resolve(resource)` | `T` | Resolves a [`Resource[T]`](./resources#symbol-resource) lazily from the request. |

Example:

```python
from quater import Quater, Request

app = Quater()


@app.get("/whoami")
async def whoami(request: Request) -> dict[str, object]:
    return {
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
        "request_id": request.context.request_id,
    }
```

Expected HTTP output:

```json
{
  "source": "api",
  "entrypoint": "server",
  "request_id": "req_..."
}
```

## State {#symbol-state}

Added in `0.1.0a1`.

Attribute container for app-level and request-level state.

```python
State() -> State
```

`app.state` lives as long as the app instance. `request.state` lives for one
request.

```python
@app.on_startup
async def startup() -> None:
    app.state.cache = {}


@app.get("/cache-size")
async def cache_size(request: Request) -> dict[str, int]:
    return {"size": len(request.app.state.cache)}
```

Do not store per-request values on `app.state`. Use `request.state` for those.

## FormData {#symbol-formdata}

Added in `0.1.0a1`.

Parsed form fields and uploaded files returned by `Request.form()`.

```python
FormData(
    *,
    fields: tuple[tuple[str, str], ...] = (),
    files: tuple[tuple[str, UploadFile], ...] = (),
) -> None
```

`FormData` behaves like a read-only mapping of string form fields. Normal
mapping lookup returns the last value for a repeated field. Use `get_all()` when
repeated field values matter.

Files live separately from fields because uploaded files are not strings. Use
`get_file()` for one file and `get_files()` for repeated file fields.

| Member | Type | Description |
| --- | --- | --- |
| `fields` | `tuple[tuple[str, str], ...]` | All string field pairs in request order. |
| `files` | `tuple[tuple[str, UploadFile], ...]` | All uploaded file pairs in request order. |
| `get_all(key)` | `tuple[str, ...]` | All string values for a field. |
| `get_file(key)` | [`UploadFile`](#symbol-uploadfile) \| None | Last uploaded file for a field. |
| `get_files(key)` | `tuple[UploadFile, ...]` | All uploaded files for a field. |

```python
from quater import Quater, Request

app = Quater()


@app.post("/profile")
async def profile(request: Request) -> dict[str, object]:
    form = await request.form()
    avatar = form.get_file("avatar")
    return {
        "name": form["name"],
        "avatar": avatar.filename if avatar else None,
    }
```

## UploadFile {#symbol-uploadfile}

Added in `0.1.0a1`.

Uploaded multipart file passed to handlers using
[`File`](./parameters#symbol-file) markers.

```python
UploadFile(
    *,
    filename: str,
    content_type: str,
    headers: Mapping[str, str] | None = None,
    content: bytes = b"",
    spool_size: int = 1048576,
) -> None
```

Quater strips path components from submitted filenames before it creates
`UploadFile`. Treat `filename` as display metadata, not a safe storage path.
`spool_size` controls when the underlying temporary file rolls from memory to
disk.

| Member | Type | Description |
| --- | --- | --- |
| `filename` | `str` | Sanitized client filename without directory components. |
| `content_type` | `str` | File part content type, or `application/octet-stream`. |
| `headers` | `dict[str, str]` | File part headers with lowercase names. |
| `size` | `int` | Uploaded byte count. |
| `file` | `BinaryIO` | Underlying spooled binary file object. |
| `closed` | `bool` | Whether Quater has closed the underlying file. |
| `read(size=-1)` | `bytes` | Read bytes from the current file position. |
| `seek(offset, whence=0)` | `int` | Move the file cursor and return the new position. |
| `close()` | `None` | Close the underlying file. Quater also closes it after the response. |

```python
from quater import File, Quater, UploadFile

app = Quater()


@app.post("/imports")
async def import_document(document: UploadFile = File()) -> dict[str, object]:
    content = await document.read()
    return {
        "filename": document.filename,
        "content_type": document.content_type,
        "size": len(content),
    }
```

## Header, Query, And Cookie Views

`Headers`, `QueryParams`, and `Cookies` are request views. They are not top-level
public imports, but you will read them from `Request`.

### Headers {#headers}

Case-insensitive mapping.

```python
token = request.headers.get("authorization")
all_cookies = request.headers.get_all("set-cookie")
raw_pairs = request.headers.raw
```

### QueryParams {#queryparams}

Parsed query-string mapping. Normal lookup returns the last value. Use
`get_all()` for repeated keys.

```python
# /search?tag=paid&tag=vip
request.query.get("tag")
request.query.get_all("tag")
```

### Cookies {#cookies}

Parsed cookie mapping.

```python
session_id = request.cookies.get("session")
```

## RequestContext {#call-context}

`request.context` tells you how the handler was reached.

| Field | Type | Description |
| --- | --- | --- |
| `source` | `"api" \| "mcp" \| "cli"` | Surface that reached the handler. |
| `entrypoint` | `"server" \| "local"` | Hosted request or local CLI call. |
| `request_id` | `str \| None` | Correlation id. |
| `tool_name` | `str \| None` | MCP tool name for tool calls. |
| `action_name` | `str \| None` | CLI action name for action calls. MCP tool calls also set it to the tool name. |

## Request Object In MCP And CLI Handlers

For MCP tool calls and CLI action calls, Quater builds a synthetic `Request`
from the action or tool arguments before calling the handler. This is true
whether the handler reads parameters via `Header()`, `Cookie()`, and `Body()`
markers, or injects `Request` directly and reads `request.headers`,
`request.cookies`, or `await request.body()`.

In both cases the handler sees the synthetic request. The outer transport
headers, such as `Authorization`, `Cookie`, `Content-Length`,
`Mcp-Protocol-Version`, and request ids, stay on the transport side and are not
visible in the handler request.

Use `request.auth` for the authenticated caller and `request.context` for
surface and action metadata:

```python
@app.get("/orders/{order_id}", tool=True, cli=True, description="Fetch one order.")
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    if request.auth is None:
        raise HTTPError(status_code=401, detail="Authentication required.")
    return {
        "order_id": order_id,
        "subject": request.auth.subject,    # authenticated caller
        "source": request.context.source,   # "mcp" or "cli"
        "action": request.context.action_name,
    }
```

## What Can Go Wrong

`Payload Too Large`
: `await request.body()` exceeded `max_body_size`.

`Malformed JSON body`
: `await request.json()` could not decode valid JSON.

`Missing required body parameter: payload`
: A handler declared a required JSON body parameter, but the request did not
  include a body. Send JSON or give the handler parameter a default.

`Malformed form body`
: `await request.form()` could not decode submitted form data.

`Unsupported form content type`
: The route expected form data, but the request did not use
  `application/x-www-form-urlencoded` or `multipart/form-data`.

`request.auth is None`
: The route had no auth hook, or auth failed before the handler. Check before
  reading `request.auth.subject`.

## Also See

- [Public API](/en/dev/api#request-and-context): usage patterns.
- [Security](/en/dev/security): request id validation and access logs.
- [Testing](/en/dev/testing): constructing requests through `TestClient`.
