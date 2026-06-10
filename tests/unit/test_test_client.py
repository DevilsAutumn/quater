from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import (
    AuthConfig,
    JSONResponse,
    Quater,
    Request,
    Response,
    StreamResponse,
    TestClient,
)
from quater.typing import AuthContext


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
async def test_test_client_puts_json_body() -> None:
    app = Quater()

    @app.put("/items/{item_id:int}")
    async def replace(item_id: int, payload: dict[str, object]) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    response = await TestClient(app).put("/items/7", json={"name": "Ada"})

    assert response.status_code == 200
    assert response.json() == {"item_id": 7, "payload": {"name": "Ada"}}


@pytest.mark.asyncio
async def test_test_client_posts_form_and_file_bodies() -> None:
    app = Quater()

    @app.post("/inspect")
    async def inspect(request: Request) -> dict[str, object]:
        form = await request.form()
        file = form.get_file("avatar")
        assert file is not None
        return {
            "name": form["name"],
            "filename": file.filename,
            "content": (await file.read()).decode("utf-8"),
            "content_type": request.headers["content-type"].split(";", 1)[0],
        }

    response = await TestClient(app).post(
        "/inspect",
        data={"name": "Ada"},
        files={"avatar": ("avatar.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Ada",
        "filename": "avatar.txt",
        "content": "hello",
        "content_type": "multipart/form-data",
    }


@pytest.mark.asyncio
async def test_test_client_rejects_ambiguous_body_arguments() -> None:
    client = TestClient(Quater())

    with pytest.raises(ValueError, match="Use either json or content"):
        await client.post("/echo", json={"name": "Ada"}, content=b"{}")
    with pytest.raises(ValueError, match="Use one request body style"):
        await client.post("/echo", json={"name": "Ada"}, data={"name": "Ada"})


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
async def test_test_client_sends_reserved_name_and_spaced_cookies() -> None:
    app = Quater()

    @app.get("/cookies")
    async def cookies(request: Request) -> dict[str, str | None]:
        return {name: request.cookies.get(name) for name in ("path", "session")}

    # "path" is a Set-Cookie attribute word; the test client must still be able
    # to send it, and a value with a space must round-trip unchanged.
    client = TestClient(app, cookies={"path": "/admin", "session": "a b"})
    response = await client.get("/cookies")

    assert response.json() == {"path": "/admin", "session": "a b"}


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
    async def authenticate(ctx: Request) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer mcp-token":
            return None
        return AuthContext(subject="mcp")

    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["mcp"])],
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
async def test_test_client_cli_helpers_cover_call_dry_run_and_manifest() -> None:
    handler_calls = 0

    async def authenticate(ctx: Request) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer cli-token":
            return None
        return AuthContext(subject="cli")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        nonlocal handler_calls
        handler_calls += 1
        assert request.auth is not None
        return {"id": id, "subject": request.auth.subject}

    client = TestClient(app)

    # AuthConfig runs before the handler: an unauthenticated call is rejected.
    unauthorized = await client.cli.call("get_user", {"id": 7})
    assert unauthorized.status_code == 401
    assert handler_calls == 0

    # An authenticated call runs the handler and returns the action envelope.
    call = await client.cli.call("get_user", {"id": 7}, token="cli-token")
    assert call.status_code == 200
    envelope = call.json()
    assert envelope["ok"] is True
    assert envelope["status_code"] == 200
    assert envelope["body"] == {"id": 7, "subject": "cli"}
    assert handler_calls == 1

    # A dry run validates without running the handler.
    dry_run = await client.cli.call(
        "get_user", {"id": 7}, token="cli-token", dry_run=True
    )
    preflight = dry_run.json()
    assert preflight["ok"] is True
    assert preflight["dry_run"] is True
    assert preflight["action"] == "get_user"
    assert handler_calls == 1

    # The manifest lists the CLI action.
    manifest = await client.cli.manifest(token="cli-token")
    assert manifest.status_code == 200
    assert [action["name"] for action in manifest.json()["actions"]] == ["get_user"]


@pytest.mark.asyncio
async def test_test_client_mcp_helper_preserves_origin_rejection() -> None:
    async def authenticate(ctx: Request) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])])

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
