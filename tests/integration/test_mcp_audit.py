from __future__ import annotations

import json

import pytest

from quater import AuthConfig, Quater, Request, ToolAuditEvent
from quater.typing import AuthContext


def mcp_body(name: str, arguments: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_successful_tool_call_emits_sanitized_audit_event() -> None:
    events: list[ToolAuditEvent] = []

    async def audit(event: ToolAuditEvent) -> None:
        events.append(event)

    async def authenticate(ctx: Request) -> AuthContext | None:
        return AuthContext(subject="user_1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])], mcp_audit=audit)

    @app.get(
        "/users/{id:int}",
        tool=True,
        description="Fetch one user.",
    )
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("get_user", {"id": 7}))
    )

    assert response.status_code == 200
    assert len(events) == 1
    assert events[0].tool_name == "get_user"
    assert events[0].subject == "user_1"
    assert events[0].success is True
    assert events[0].arguments == {"id": "<redacted>"}
    assert events[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_failed_tool_call_emits_failure_audit_event() -> None:
    events: list[ToolAuditEvent] = []

    async def audit(event: ToolAuditEvent) -> None:
        events.append(event)

    async def authenticate(ctx: Request) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])], mcp_audit=audit)

    @app.get("/boom", tool=True, description="Raise a handler error.")
    async def boom() -> dict[str, bool]:
        raise RuntimeError("boom")

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("boom", {}))
    )
    body = json.loads(response.body)

    assert body["result"]["isError"] is True
    assert len(events) == 1
    assert events[0].tool_name == "boom"
    assert events[0].success is False


@pytest.mark.asyncio
async def test_audit_hook_failure_returns_json_rpc_error_without_leaking_detail() -> (
    None
):
    async def audit(event: ToolAuditEvent) -> None:
        raise RuntimeError("database password leaked")

    async def authenticate(ctx: Request) -> AuthContext | None:
        return AuthContext(subject="user_1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])], mcp_audit=audit)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("get_user", {"id": 7}))
    )
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["error"] == {"code": -32603, "message": "Audit hook failed"}
    assert b"password" not in response.body


@pytest.mark.asyncio
async def test_audit_hook_failure_in_debug_includes_exception_type() -> None:
    async def audit(event: ToolAuditEvent) -> None:
        raise RuntimeError("audit backend unavailable")

    async def authenticate(ctx: Request) -> AuthContext | None:
        return AuthContext(subject="user_1")

    app = Quater(
        debug=True, auth=[AuthConfig(authenticate, surfaces=["mcp"])], mcp_audit=audit
    )

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(
        Request(method="POST", path="/mcp", body=mcp_body("get_user", {"id": 7}))
    )
    body = json.loads(response.body)

    assert body["error"] == {
        "code": -32603,
        "message": "Audit hook failed: RuntimeError: audit backend unavailable",
    }
