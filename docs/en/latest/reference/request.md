# Request Reference

This page documents `Request`, `State`, and the request view objects available
from handlers.

## Prerequisites

Read [Public API](/en/latest/api#binding) for binding rules. Use `Request` when
you need headers, cookies, raw body access, auth, state, or call-source context.

```python
from quater import Request, State
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

## What Can Go Wrong

`Payload Too Large`
: `await request.body()` exceeded `max_body_size`.

`Malformed JSON body`
: `await request.json()` could not decode valid JSON.

`request.auth is None`
: The route had no auth hook, or auth failed before the handler. Check before
  reading `request.auth.subject`.

## Also See

- [Public API](/en/latest/api#request-and-context): usage patterns.
- [Security](/en/latest/security): request id validation and access logs.
- [Testing](/en/latest/testing): constructing requests through `TestClient`.
