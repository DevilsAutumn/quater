from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import JSONResponse, Quater, Request, Response, StreamResponse, TestClient
from quater.typing import AuthContext, AuthRequest


@pytest.mark.asyncio
async def test_test_client_sends_query_headers_and_default_host() -> None:
    app = Quater(allowed_hosts=["testserver"])

    @app.get("/items")
    async def items(page: int, request: Request) -> dict[str, object]:
        return {
            "page": page,
            "tags": request.query.get_all("tag"),
            "host": request.headers["host"],
            "agent": request.headers["x-test-agent"],
        }

    client = TestClient(app)
    response = await client.get(
        "/items",
        params={"page": 2, "tag": ["red", "blue"]},
        headers={"x-test-agent": "unit"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "page": 2,
        "tags": ["red", "blue"],
        "host": "testserver",
        "agent": "unit",
    }
    assert response.headers["content-type"] == "application/json"
    assert response.is_success is True


@pytest.mark.asyncio
async def test_test_client_accepts_query_pairs_for_repeated_keys() -> None:
    app = Quater()

    @app.get("/items")
    async def items(request: Request) -> dict[str, object]:
        return {
            "page": request.query["page"],
            "tags": request.query.get_all("tag"),
        }

    response = await TestClient(app).get(
        "/items",
        params=[("page", "2"), ("tag", "red"), ("tag", "blue")],
    )

    assert response.status_code == 200
    assert response.json() == {"page": "2", "tags": ["red", "blue"]}


@pytest.mark.asyncio
async def test_test_client_posts_json_body() -> None:
    app = Quater()

    @app.post("/echo")
    async def echo(payload: dict[str, object], request: Request) -> dict[str, object]:
        return {
            "payload": payload,
            "content_type": request.headers["content-type"],
        }

    response = await TestClient(app).post("/echo", json={"name": "Ada"})

    assert response.status_code == 200
    assert response.json() == {
        "payload": {"name": "Ada"},
        "content_type": "application/json",
    }


@pytest.mark.asyncio
async def test_test_client_rejects_ambiguous_body_arguments() -> None:
    client = TestClient(Quater())

    with pytest.raises(ValueError, match="Use either json or content"):
        await client.post("/echo", json={"name": "Ada"}, content=b"{}")


@pytest.mark.asyncio
async def test_test_client_rejects_invalid_request_targets() -> None:
    client = TestClient(Quater())

    with pytest.raises(ValueError, match="must start with '/'"):
        await client.get("health")
    with pytest.raises(ValueError, match="must not include URL fragments"):
        await client.get("/health#local")


@pytest.mark.asyncio
async def test_test_client_context_manager_runs_lifespan() -> None:
    app = Quater()
    events: list[str] = []

    @app.on_startup
    async def startup() -> None:
        events.append("startup")

    @app.on_shutdown
    async def shutdown() -> None:
        events.append("shutdown")

    async with TestClient(app):
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_test_client_cookie_jar_persists_response_cookies() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> Response:
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


@pytest.mark.asyncio
async def test_test_client_per_request_cookie_overrides_cookie_jar() -> None:
    app = Quater()

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app, cookies={"session": "jar"})
    response = await client.get("/me", cookies={"session": "request"})

    assert response.json() == {"session": "request"}


@pytest.mark.asyncio
async def test_test_client_collects_streaming_responses() -> None:
    app = Quater()

    async def chunks() -> AsyncIterator[bytes]:
        yield b"hello"
        yield b" "
        yield b"world"

    @app.get("/stream")
    async def stream() -> StreamResponse:
        return StreamResponse(chunks(), content_type="text/plain")

    response = await TestClient(app).get("/stream")

    assert response.status_code == 200
    assert response.body == b"hello world"
    assert response.text == "hello world"


@pytest.mark.asyncio
async def test_test_client_mcp_helpers_cover_initialize_list_and_call() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer mcp-token":
            return None
        return AuthContext(subject="mcp")

    app = Quater(
        mcp_auth=authenticate,
        mcp_allowed_origins=["https://client.example"],
    )

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {"id": id, "subject": request.auth.subject}

    client = TestClient(app)
    initialize = await client.mcp.initialize(
        token="mcp-token",
        origin="https://client.example",
    )
    tools = await client.mcp.tools_list(
        token="mcp-token",
        origin="https://client.example",
    )
    call = await client.mcp.tools_call(
        "get_user",
        {"id": 7},
        token="mcp-token",
        origin="https://client.example",
    )

    assert initialize.status_code == 200
    assert initialize.json()["result"]["serverInfo"]["name"] == "quater"
    assert tools.json()["result"]["tools"][0]["name"] == "get_user"
    assert call.json()["result"] == {
        "content": [{"type": "text", "text": '{"id":7,"subject":"mcp"}'}],
        "isError": False,
    }


@pytest.mark.asyncio
async def test_test_client_mcp_helper_preserves_origin_rejection() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(mcp_auth=authenticate)

    @app.get("/ping", tool=True, description="Ping.")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    response = await TestClient(app).mcp.tools_call(
        "ping",
        token="mcp-token",
        origin="https://evil.example",
    )

    assert response.status_code == 403
    assert response.text == "Invalid MCP Origin"
