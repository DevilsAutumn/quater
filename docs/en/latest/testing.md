# Testing Quater Apps

This page shows how to test Quater handlers, auth, resources, streams, cookies,
lifespan hooks, and MCP tools without starting a server.

## Prerequisites

Install the test dependencies for your app. The examples use
[pytest-asyncio](https://pytest-asyncio.readthedocs.io/) and run with
[uv](https://docs.astral.sh/uv/).

```bash
uv add --dev pytest pytest-asyncio
uv run pytest
```

## TestClient Is Not A Mock

`TestClient` exercises the real Quater request path:

- request object creation
- host and body checks
- route matching
- middleware
- auth
- parameter binding
- resources
- cookies
- response serialization
- lifespan hooks
- MCP helpers

It skips Granian, sockets, ports, process signals, and worker behavior. Use a
real server only for adapter, deployment, or benchmark tests.

## A Runnable Test

```python
import pytest

from quater import Quater, TestClient


@pytest.mark.asyncio
async def test_health() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

Expected output:

```text
1 passed
```

## Request Data

```python
import pytest

from quater import Quater, Request, TestClient


@pytest.mark.asyncio
async def test_query_params_are_bound() -> None:
    app = Quater()

    @app.get("/search")
    async def search(q: str, page: int, request: Request) -> dict[str, object]:
        return {
            "q": q,
            "page": page,
            "tags": request.query.get_all("tag"),
        }

    response = await TestClient(app).get(
        "/search",
        params=[("q", "orders"), ("page", 2), ("tag", "paid"), ("tag", "vip")],
    )

    assert response.status_code == 200
    assert response.json() == {"q": "orders", "page": 2, "tags": ["paid", "vip"]}
```

Use `json=` for JSON bodies. Do not pass `json=` and `content=` together.

Expected error:

```text
Use either json or content, not both
```

## Auth Boundaries

Test the denied path and the allowed path. Also prove the handler did not run
when auth failed.

```python
import pytest

from quater import AuthContext, AuthRequest, Quater, Request, TestClient


@pytest.mark.asyncio
async def test_auth_blocks_handler() -> None:
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
    assert allowed.json() == {"subject": "user_123"}
    assert calls == 1
```

## Lifespan And State

Use `async with TestClient(app)` when tests depend on startup or shutdown hooks:

```python
import pytest

from quater import Quater, Request, TestClient


@pytest.mark.asyncio
async def test_startup_state() -> None:
    app = Quater()

    @app.on_startup
    async def startup() -> None:
        app.state.ready = True

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, bool]:
        return {"ready": request.app.state.ready}

    async with TestClient(app) as client:
        response = await client.get("/ready")

    assert response.json() == {"ready": True}
```

## Resources

Resource cleanup runs after the response path completes.

```python
from collections.abc import AsyncIterator

import pytest

from quater import Quater, Resource, TestClient


@pytest.mark.asyncio
async def test_resource_cleanup_runs_after_response() -> None:
    events: list[str] = []

    async def resource() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "db-session"
        finally:
            events.append("close")

    app = Quater()
    db = Resource(resource, name="db")

    @app.get("/orders/{order_id}", inject={"session": db})
    async def get_order(order_id: str, session: str) -> dict[str, str]:
        events.append(session)
        return {"order_id": order_id}

    response = await TestClient(app).get("/orders/ord_1001")

    assert response.status_code == 200
    assert events == ["open", "db-session", "close"]
```

## Cookies

`TestClient` keeps a small cookie jar:

```python
import pytest

from quater import JSONResponse, Quater, Request, TestClient


@pytest.mark.asyncio
async def test_cookie_flow() -> None:
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
    await client.get("/login")
    response = await client.get("/me")

    assert response.json() == {"session": "abc123"}
```

## Streams

The test client collects stream chunks into `response.body`:

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

    assert response.body == b"hello world"
```

## MCP Tools

Use `client.mcp` to test MCP without a separate MCP client:

```python
import pytest

from quater import AuthContext, AuthRequest, Quater, TestClient


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer mcp-token":
        return None
    return AuthContext(subject="agent_123")


@pytest.mark.asyncio
async def test_mcp_tool_call() -> None:
    app = Quater(
        mcp_auth=authenticate,
        mcp_allowed_origins=["https://client.example"],
    )

    @app.get("/orders/{order_id}", tool=True, description="Fetch one order.")
    async def get_order(order_id: str) -> dict[str, str]:
        return {"order_id": order_id}

    async with TestClient(app) as client:
        response = await client.mcp.tools_call(
            "get_order",
            {"order_id": "ord_1001"},
            token="mcp-token",
            origin="https://client.example",
        )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
```

Test auth and origin failures:

```python
denied = await client.mcp.tools_list(token="wrong-token")
bad_origin = await client.mcp.tools_list(
    token="mcp-token",
    origin="https://evil.example",
)

assert denied.status_code == 401
assert bad_origin.status_code == 403
```

## What Can Go Wrong

`TestClient requires a Quater application`
: Pass a `Quater` instance, not an ASGI wrapper or module object.

`Test client paths must start with '/'`
: Use paths like `/health`, not `health`.

`Test client paths must not include URL fragments`
: Remove `#fragment` from the path.

`Use either json or content, not both`
: Pick one body input style.

`Malformed JSON body`
: The handler called `await request.json()` or bound a body parameter, but the
  request body was not valid JSON.

## Also See

- [Resources and Injection](/en/latest/resources): understand cleanup behavior.
- [MCP](/en/latest/mcp): understand what `client.mcp` sends.
- [Reference: Testing](/en/latest/reference/testing): exact client signatures.
- [Deployment](/en/latest/deployment): when you need a real server test.
