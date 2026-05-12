# Testing

Quater tests should prove the behavior your app promises, not just that a route
returns `200`.

Use `TestClient` when you want to call a Quater app in process. It runs through
the same request handling path as the framework, but it does not start Granian,
ASGI, WSGI, or a listening port.

```python
from quater import Quater, TestClient

app = Quater()


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


async def test_health() -> None:
    async with TestClient(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

Run tests with pytest:

```bash
uv run pytest
```

Example output:

```text
12 passed in 0.18s
```

::: tip What the client is for
Use the in-process client for application behavior, auth boundaries, binding,
serialization, cookies, lifespan hooks, and MCP tool behavior.

Use a real server only when you are testing server behavior itself: Granian
startup, process signals, worker settings, network timeouts, or benchmarks.
:::

## Basic Pattern

Most Quater tests should follow this shape:

1. Create a small app for the scenario.
2. Register only the route and hooks needed for the behavior.
3. Call the route with `TestClient`.
4. Assert the observable result and the important side effect.

```python
import pytest

from quater import Quater, Request, TestClient


@pytest.mark.asyncio
async def test_query_params_are_bound() -> None:
    app = Quater()

    @app.get("/search")
    async def search(q: str, page: int, request: Request) -> dict[str, object]:
        return {
            "query": q,
            "page": page,
            "tags": request.query.get_all("tag"),
        }

    response = await TestClient(app).get(
        "/search",
        params={
            "q": "ada",
            "page": 2,
            "tag": ["python", "mcp"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "query": "ada",
        "page": 2,
        "tags": ["python", "mcp"],
    }
```

`params=` accepts mappings for normal use and a sequence of pairs when repeated
keys are clearer:

```python
response = await TestClient(app).get(
    "/search",
    params=[("tag", "python"), ("tag", "mcp")],
)
```

## Request Bodies

Use `json=` for JSON request bodies. Quater sets `content-type:
application/json` for you.

```python
import msgspec
import pytest

from quater import Quater, Request, TestClient


class CreateUser(msgspec.Struct):
    name: str
    age: int


@pytest.mark.asyncio
async def test_json_body_is_bound() -> None:
    app = Quater()

    @app.post("/users")
    async def create_user(user: CreateUser, request: Request) -> dict[str, object]:
        return {
            "name": user.name,
            "age": user.age,
            "content_type": request.headers["content-type"],
        }

    response = await TestClient(app).post(
        "/users",
        json={"user": {"name": "Ada", "age": 37}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Ada",
        "age": 37,
        "content_type": "application/json",
    }
```

Use `content=` when the body is already encoded:

```python
response = await TestClient(app).post("/events", content=b"raw payload")
```

Passing both `json=` and `content=` is an error. That is intentional. Tests
should not hide ambiguous request setup.

## Auth Boundaries

For protected routes, test both the allowed and denied path. The denied path is
not boring. It proves the handler did not run when auth failed.

```python
import pytest

from quater import AuthContext, AuthRequest, Quater, Request, TestClient


@pytest.mark.asyncio
async def test_route_auth_blocks_missing_token() -> None:
    calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer user-token":
            return None
        return AuthContext(subject="user_123")

    app = Quater()

    @app.get("/me", auth=authenticate)
    async def me(request: Request) -> dict[str, str]:
        nonlocal calls
        calls += 1
        assert request.auth is not None
        return {"subject": request.auth.subject}

    denied = await TestClient(app).get("/me")
    allowed = await TestClient(app).get(
        "/me",
        headers={"authorization": "Bearer user-token"},
    )

    assert denied.status_code == 401
    assert denied.text == "Unauthorized"
    assert allowed.status_code == 200
    assert allowed.json() == {"subject": "user_123"}
    assert calls == 1
```

::: warning Test the boundary, not the implementation detail
Do not only assert `401`. Also assert that the protected work did not happen.
That catches the bad class of bug where a response is denied after the handler
already touched data.
:::

## Cookies

`TestClient` keeps a small cookie jar. Cookies returned by one response are sent
with later requests from the same client.

```python
import pytest

from quater import JSONResponse, Quater, Request, TestClient


@pytest.mark.asyncio
async def test_cookie_session_flow() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> JSONResponse:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "session=abc123; Path=/; HttpOnly"},
        )

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app)

    login_response = await client.get("/login")
    me_response = await client.get("/me")

    assert login_response.status_code == 200
    assert me_response.json() == {"session": "abc123"}
```

Use per-request `cookies=` when a test needs a temporary cookie value without
changing the client setup:

```python
response = await client.get("/me", cookies={"session": "override"})
```

## Lifespan

Use `async with TestClient(app)` when the test depends on startup or shutdown
hooks.

```python
import pytest

from quater import Quater, TestClient


@pytest.mark.asyncio
async def test_lifespan_hooks_run() -> None:
    events: list[str] = []
    app = Quater()

    @app.on_startup
    async def startup() -> None:
        events.append("startup")

    @app.on_shutdown
    async def shutdown() -> None:
        events.append("shutdown")

    async with TestClient(app):
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]
```

You can also call `await client.startup()` and `await client.shutdown()` manually
when that reads better for the test.

## Error Responses

Good error tests prove two things:

- the caller receives a safe, useful response
- sensitive details do not leak

```python
import pytest

from quater import Quater, TestClient


@pytest.mark.asyncio
async def test_internal_error_is_safe() -> None:
    app = Quater()

    @app.get("/boom")
    async def boom() -> dict[str, bool]:
        raise RuntimeError("database password leaked here")

    response = await TestClient(app).get("/boom")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "password" not in response.text
```

For custom exceptions, assert the mapped response and the status code:

```python
from quater import HTTPError


@app.get("/missing")
async def missing() -> dict[str, bool]:
    raise HTTPError("Not found", status_code=404)
```

## Streams

The test client collects `StreamResponse` bodies into `response.body`. That keeps
tests simple while still running the streaming response path.

```python
from collections.abc import AsyncIterator

import pytest

from quater import Quater, StreamResponse, TestClient


async def chunks() -> AsyncIterator[bytes]:
    yield b"hello "
    yield b"world"


@pytest.mark.asyncio
async def test_stream_response() -> None:
    app = Quater()

    @app.get("/stream")
    async def stream() -> StreamResponse:
        return StreamResponse(chunks())

    response = await TestClient(app).get("/stream")

    assert response.status_code == 200
    assert response.body == b"hello world"
```

## MCP Tools

Routes exposed with `tool=True` can be tested through `client.mcp`.
`client.mcp` is an `MCPTestClient` created by `TestClient`; you usually do not
need to instantiate it yourself.

This is the right place to test MCP auth, origin checks, argument binding, and
the JSON-RPC shape the client sees.

```python
import pytest

from quater import AuthContext, AuthRequest, Quater, TestClient


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer mcp-token":
        return None
    return AuthContext(subject="agent_1")


@pytest.mark.asyncio
async def test_mcp_tool_call() -> None:
    app = Quater(
        mcp_auth=authenticate,
        mcp_allowed_origins=["https://client.example"],
    )

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    async with TestClient(app) as client:
        response = await client.mcp.tools_call(
            "get_user",
            {"id": 7},
            token="mcp-token",
            origin="https://client.example",
        )

    assert response.status_code == 200
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": '{"id":7}'}],
            "isError": False,
        },
    }
```

Test rejection paths too:

```python
denied = await client.mcp.tools_list(
    token="wrong-token",
    origin="https://client.example",
)
bad_origin = await client.mcp.tools_list(
    token="mcp-token",
    origin="https://evil.example",
)

assert denied.status_code == 401
assert bad_origin.status_code == 403
```

::: tip MCP tests should still test route auth
`mcp_auth` protects the MCP transport. Route `auth=` protects the handler route.
If a tool route has both, include at least one test proving the route-level auth
still runs for `tools/call`.
:::

## What To Test

For a real app, a useful test suite usually has these layers:

- **Route behavior:** path/query/body binding, response shape, status codes.
- **Security boundaries:** missing token, wrong token, wrong origin, forbidden
  route, oversized body, and handler not called on denied requests.
- **State behavior:** cookies, lifespan setup, in-memory stores, cleanup.
- **MCP behavior:** `tools/list` visibility, `tools/call` success, bad
  arguments, auth failure, origin failure, approval failure if the route needs
  approval.
- **Transport behavior:** one or two integration tests through the server stack
  if you are changing adapters or deployment settings.

Avoid tests that only repeat the implementation:

```python
assert response.status_code == 200
```

That is rarely enough by itself. Better:

```python
assert response.status_code == 200
assert response.json() == {"id": 7, "status": "shipped"}
assert audit_events == ["order_status_changed"]
```

The second version checks the result and the important side effect. That is the
test that catches real bugs.

## Reference

`TestClient` accepts:

- `host`
- `scheme`
- `client`
- `headers`
- `cookies`

Request helpers accept:

- `params`
- `headers`
- `cookies`
- `json`
- `content`

`TestResponse` exposes:

- `status_code`
- `headers`
- `body`
- `text`
- `json()`
- `is_success`

MCP helpers live under `client.mcp`:

- `initialize(...)`
- `tools_list(...)`
- `tools_call(...)`
- `request(...)`

`client.mcp` is an `MCPTestClient`. It is exported for typing and advanced
tests, but the normal pattern is still:

```python
client = TestClient(app)
response = await client.mcp.tools_list(token="mcp-token")
```
