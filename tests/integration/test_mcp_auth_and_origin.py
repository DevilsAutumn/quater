from __future__ import annotations

import json

import pytest

from quater import CORSConfig, Quater, Request
from quater.typing import AuthContext, AuthRequest


def mcp_body(name: str, arguments: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    ).encode("utf-8")


def initialize_body() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_mcp_uses_same_auth_denial_policy_as_http() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return None

    app = Quater(mcp_auth=authenticate)

    @app.get(
        "/private",
        tool=True,
        auth=authenticate,
        description="Read private data.",
    )
    async def private() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("private", {}))
    )

    assert response.status_code == 401
    assert response.body == b"Unauthorized"


@pytest.mark.asyncio
async def test_auth_hook_sees_tool_source_for_tools_call() -> None:
    seen: list[tuple[str, str | None]] = []

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        seen.append((ctx.context.source, ctx.context.tool_name))
        return AuthContext(subject="user_1")

    app = Quater(mcp_auth=authenticate)

    @app.get("/me", tool=True, auth=authenticate, description="Read current user.")
    async def me(request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {
            "subject": request.auth.subject,
            "source": request.context.source,
            "tool": request.context.tool_name,
        }

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("me", {}))
    )
    body = json.loads(response.body)

    assert seen == [("tool", "me"), ("tool", "me")]
    assert body["result"]["content"][0]["text"] == (
        '{"subject":"user_1","source":"tool","tool":"me"}'
    )


@pytest.mark.asyncio
async def test_invalid_mcp_origin_rejects_before_auth_and_handler() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(
        mcp_auth=authenticate,
        mcp_allowed_origins=["https://app.example.com"],
    )

    @app.get(
        "/private",
        tool=True,
        auth=authenticate,
        description="Read private data.",
    )
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"origin": "https://evil.example.com"},
            body=mcp_body("private", {}),
        )
    )

    assert response.status_code == 403
    assert response.body == b"Invalid MCP Origin"
    assert auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_valid_mcp_origin_can_use_cors_origin_policy() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(
        cors=CORSConfig(allowed_origins=("https://app.example.com",)),
        mcp_auth=authenticate,
    )

    @app.get("/ping", tool=True, description="Check tool connectivity.")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"origin": "https://app.example.com"},
            body=mcp_body("ping", {}),
        )
    )

    assert response.status_code == 200
    assert dict(response.headers)["access-control-allow-origin"] == (
        "https://app.example.com"
    )


@pytest.mark.asyncio
async def test_mcp_origin_header_is_rejected_without_an_allowlist() -> None:
    auth_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="mcp")

    app = Quater(mcp_auth=authenticate)

    @app.get("/ping", tool=True, description="Check tool connectivity.")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"origin": "https://evil.example.com"},
            body=mcp_body("ping", {}),
        )
    )

    assert response.status_code == 403
    assert response.body == b"Invalid MCP Origin"
    assert auth_calls == 0


@pytest.mark.asyncio
async def test_cors_wildcard_does_not_allow_mcp_browser_origins() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(cors=CORSConfig(allowed_origins=("*",)), mcp_auth=authenticate)

    @app.get("/ping", tool=True, description="Check tool connectivity.")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"origin": "https://evil.example.com"},
            body=mcp_body("ping", {}),
        )
    )

    assert response.status_code == 403
    assert response.body == b"Invalid MCP Origin"


@pytest.mark.asyncio
async def test_mcp_auth_protects_initialize_and_tools_list() -> None:
    seen: list[tuple[str, str | None]] = []

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        seen.append((ctx.context.source, ctx.context.tool_name))
        if ctx.headers.get("authorization") != "Bearer mcp":
            return None
        return AuthContext(subject="mcp")

    app = Quater(mcp_auth=authenticate)

    @app.get("/ping", tool=True, description="Check tool connectivity.")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    denied_initialize = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"content-type": "application/json"},
            body=initialize_body(),
        )
    )
    allowed_initialize = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={
                "authorization": "Bearer mcp",
                "content-type": "application/json",
            },
            body=initialize_body(),
        )
    )
    denied_list = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"content-type": "application/json"},
            body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode(
                "utf-8"
            ),
        )
    )

    assert denied_initialize.status_code == 401
    assert allowed_initialize.status_code == 200
    assert denied_list.status_code == 401
    assert seen == [("mcp", None), ("mcp", None), ("mcp", None)]


@pytest.mark.asyncio
async def test_initialize_auth_does_not_authenticate_later_tool_calls() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer mcp":
            return None
        return AuthContext(subject="mcp")

    app = Quater(mcp_auth=authenticate)

    @app.get("/private", tool=True, description="Read private data.")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    initialized = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={
                "authorization": "Bearer mcp",
                "content-type": "application/json",
            },
            body=initialize_body(),
        )
    )
    denied_tool = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("private", {}))
    )

    assert initialized.status_code == 200
    assert denied_tool.status_code == 401


@pytest.mark.asyncio
async def test_different_route_auth_still_runs_after_mcp_auth() -> None:
    calls: list[str] = []

    async def authenticate_mcp(ctx: AuthRequest) -> AuthContext | None:
        calls.append(f"mcp:{ctx.context.source}:{ctx.context.tool_name}")
        return AuthContext(subject="mcp")

    async def authenticate_route(ctx: AuthRequest) -> AuthContext | None:
        calls.append(f"route:{ctx.context.source}:{ctx.context.tool_name}")
        return AuthContext(subject="route")

    app = Quater(mcp_auth=authenticate_mcp)

    @app.get(
        "/private",
        tool=True,
        auth=authenticate_route,
        description="Read private data.",
    )
    async def private(request: Request) -> dict[str, str]:
        assert request.auth is not None
        return {"subject": request.auth.subject}

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("private", {}))
    )

    assert response.status_code == 200
    assert calls == ["mcp:tool:private", "route:tool:private"]
    assert b'\\"subject\\":\\"route\\"' in response.body


@pytest.mark.asyncio
async def test_same_route_auth_runs_again_with_real_tool_route_path() -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        calls.append((ctx.method, ctx.path, ctx.context.tool_name))
        if ctx.path == "/mcp":
            return AuthContext(subject="transport")
        if ctx.path == "/private":
            return None
        return AuthContext(subject="unexpected")

    app = Quater(mcp_auth=authenticate)

    @app.get(
        "/private",
        tool=True,
        auth=authenticate,
        description="Read private data.",
    )
    async def private() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("private", {}))
    )
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["result"] == {
        "content": [{"type": "text", "text": "Unauthorized"}],
        "isError": True,
    }
    assert calls == [("POST", "/mcp", "private"), ("GET", "/private", "private")]
