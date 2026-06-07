---
description: Reference for Quater's TestClient, TestResponse, MCPTestClient, and CliTestClient testing utilities.
---

# Testing Reference

This page documents `TestClient`, `TestResponse`, `MCPTestClient`, and
`CliTestClient`.

## Prerequisites

Read [Testing Quater Apps](/en/dev/testing). The clients are async and work
well with [pytest-asyncio](https://pytest-asyncio.readthedocs.io/).

```python
from quater import CliTestClient, MCPTestClient, TestClient, TestResponse
```

## TestClient {#symbol-testclient}

Added in `0.1.0a1`.

Async in-process client for Quater apps.

```python
TestClient(
    app: object,
    *,
    host: str = "testserver",
    scheme: Literal["http", "https"] = "http",
    client: str = "127.0.0.1",
    headers: HeaderItems | Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `app` | `object` | required | Quater app under test. |
| `host` | `str` | `"testserver"` | Host header for requests. |
| `scheme` | `"http" \| "https"` | `"http"` | Request scheme. |
| `client` | `str` | `"127.0.0.1"` | Client address. |
| `headers` | `HeaderItems \| Mapping[str, str] \| None` | `None` | Default request headers. |
| `cookies` | `Mapping[str, str] \| None` | `None` | Initial cookie jar. |

Methods:

| Method | Return | Description |
| --- | --- | --- |
| `request(method, path, ...)` | [`TestResponse`](#symbol-testresponse) | Send any method. |
| `get`, `post`, `put`, `patch`, `delete` | [`TestResponse`](#symbol-testresponse) | Convenience request methods. |
| `set_cookie(name, value)` | `None` | Store a cookie. |
| `clear_cookies()` | `None` | Clear cookie jar. |
| `startup()` | `None` | Run startup hooks. |
| `shutdown()` | `None` | Run shutdown hooks. |

`request()` signature:

```python
request(
    method: str,
    path: str,
    *,
    params: QueryParams | None = None,
    headers: HeaderItems | Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
    json: object = None,
    content: bytes | bytearray | memoryview | str | None = None,
    data: FormDataInput | None = None,
    files: FilesInput | None = None,
) -> TestResponse
```

Example:

```python
from quater import Quater, TestClient

app = Quater()


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


async def test_health() -> None:
    response = await TestClient(app).get("/health")
    assert response.json() == {"ok": True}
```

## TestResponse {#symbol-testresponse}

Added in `0.1.0a1`.

Collected response returned by `TestClient`.

```python
TestResponse(*, status_code: int, headers: HeaderItems, body: bytes)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `status_code` | `int` | required | Response status. |
| `headers` | `HeaderItems` | required | Response headers. |
| `body` | `bytes` | required | Collected body. |

| Member | Type | Description |
| --- | --- | --- |
| `text` | `str` | UTF-8 decoded body. |
| `is_success` | `bool` | `True` for `2xx` and `3xx`. |
| `json()` | `Any` | Parsed JSON body. |

## MCPTestClient {#symbol-mcptestclient}

Added in `0.1.0a1`.

JSON-RPC helper bound to a `TestClient`. Use `client.mcp` in most tests.

```python
MCPTestClient(client: TestClient) -> None
```

Methods:

| Method | Return | Description |
| --- | --- | --- |
| `initialize(...)` | [`TestResponse`](#symbol-testresponse) | Sends MCP `initialize`. |
| `tools_list(...)` | [`TestResponse`](#symbol-testresponse) | Sends `tools/list`. |
| `tools_call(name, arguments, ...)` | [`TestResponse`](#symbol-testresponse) | Sends `tools/call`. |
| `request(payload, ...)` | [`TestResponse`](#symbol-testresponse) | Sends a custom JSON-RPC payload. |

`tools_call()` signature:

```python
tools_call(
    name: str,
    arguments: Mapping[str, object] | None = None,
    *,
    request_id: str | int = 1,
    token: str | None = None,
    origin: str | None = None,
    approval_token: str | None = None,
    meta: Mapping[str, object] | None = None,
    protocol_version: str = "2025-11-25",
    headers: HeaderItems | Mapping[str, str] | None = None,
) -> TestResponse
```

## CliTestClient {#symbol-clitestclient}

Added in `0.1.0b1`.

Remote-action helper bound to a `TestClient`. Use `client.cli` in most tests. It
calls actions and reads the action manifest through the same remote-action
endpoints as the Quater CLI.

```python
CliTestClient(client: TestClient) -> None
```

Methods:

| Method | Return | Description |
| --- | --- | --- |
| `call(action, arguments, ...)` | [`TestResponse`](#symbol-testresponse) | Calls an exposed CLI action. |
| `manifest(...)` | [`TestResponse`](#symbol-testresponse) | Reads the action manifest. |

`call()` signature:

```python
call(
    action: str,
    arguments: Mapping[str, object] | None = None,
    *,
    token: str | None = None,
    dry_run: bool = False,
    approval_token: str | None = None,
    headers: HeaderItems | Mapping[str, str] | None = None,
) -> TestResponse
```

Both methods return the raw `TestResponse`. A successful action body is the
`{ok, status_code, body}` envelope; a `dry_run=True` call returns the preflight
payload instead of running the handler.

## What Can Go Wrong

`TestClient requires a Quater application`
: Pass the `Quater` app object, not `app.asgi` or a module.

`Test client paths must start with '/'`
: Use `/health`.

`Test client paths must not include URL fragments`
: Remove `#...` from the path.

`Use either json or content, not both`
: Pick one body input.

`Use one request body style`
: Use only one of `json=`, `content=`, or `data=`. You may combine `data=`
  with `files=` for multipart upload tests.

## Also See

- [Testing Quater Apps](/en/dev/testing): examples across auth, resources,
  cookies, streams, and MCP.
- [Reference: Request](./request): request object created by the client.
- [Reference: Responses](./responses): response conversion used in tests.
