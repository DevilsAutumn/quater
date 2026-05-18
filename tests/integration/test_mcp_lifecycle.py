from __future__ import annotations

import json

import pytest

from quater import AuthContext, AuthRequest, Quater, Request, __version__
from quater.tools.mcp import LATEST_PROTOCOL_VERSION


async def allow_mcp_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="mcp")


async def mcp_post(
    app: Quater,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, object]]:
    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers=headers or {"content-type": "application/json"},
            body=json.dumps(payload).encode("utf-8"),
        )
    )
    body = json.loads(response.body) if response.body else {}
    return response.status_code, response.body, body


async def raw_mcp_post(
    app: Quater,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, object]]:
    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers=headers or {"content-type": "application/json"},
            body=body,
        )
    )
    payload = json.loads(response.body) if response.body else {}
    return response.status_code, response.body, payload


def require_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
async def test_initialize_negotiates_protocol_and_declares_tool_capability() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    status, _, body = await mcp_post(
        app,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        },
        headers={
            "authorization": "Bearer mcp",
            "content-type": "application/json",
        },
    )

    result = require_object(body["result"])
    server_info = require_object(result["serverInfo"])
    assert status == 200
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {}}
    assert server_info == {
        "name": "quater",
        "title": "Quater",
        "version": __version__,
    }


@pytest.mark.asyncio
async def test_initialize_falls_back_to_latest_supported_protocol() -> None:
    status, _, body = await mcp_post(
        Quater(),
        {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2099-01-01",
                "capabilities": {},
                "clientInfo": {"name": "future-client", "version": "1.0.0"},
            },
        },
    )

    result = require_object(body["result"])
    assert status == 200
    assert result["protocolVersion"] == LATEST_PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_initialized_notification_returns_accepted_without_body() -> None:
    status, body_bytes, body = await mcp_post(
        Quater(),
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
    )

    assert status == 202
    assert body_bytes == b""
    assert body == {}


@pytest.mark.asyncio
async def test_cursor_style_startup_sequence_can_list_tools_after_initialize() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    initialize_status, _, initialize_body = await mcp_post(
        app,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "cursor-like-client", "version": "1.0.0"},
            },
        },
        headers={
            "authorization": "Bearer mcp",
            "content-type": "application/json",
        },
    )
    initialized_status, initialized_bytes, _ = await mcp_post(
        app,
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
        headers={
            "content-type": "application/json",
            "authorization": "Bearer mcp",
            "mcp-protocol-version": "2025-06-18",
        },
    )
    list_status, _, list_body = await mcp_post(
        app,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={
            "content-type": "application/json",
            "authorization": "Bearer mcp",
            "mcp-protocol-version": "2025-06-18",
        },
    )

    assert initialize_status == 200
    assert require_object(initialize_body["result"])["protocolVersion"] == "2025-06-18"
    assert initialized_status == 202
    assert initialized_bytes == b""
    assert list_status == 200
    tools = require_object(list_body["result"])["tools"]
    assert tools == [
        {
            "name": "get_user",
            "description": "Fetch one user.",
            "inputSchema": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "additionalProperties": False,
                "required": ["id"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_initialize_with_invalid_params_returns_json_rpc_error() -> None:
    invalid_params: list[dict[str, object]] = [
        {},
        {
            "protocolVersion": "2025-06-18",
            "capabilities": [],
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client"},
        },
    ]

    for params in invalid_params:
        status, _, body = await mcp_post(
            Quater(),
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": params,
            },
        )

        assert status == 200
        assert body["error"] == {"code": -32602, "message": "Invalid params"}


@pytest.mark.asyncio
async def test_request_methods_require_json_rpc_id() -> None:
    status, _, body = await mcp_post(
        Quater(),
        {"jsonrpc": "2.0", "method": "tools/list"},
    )

    assert status == 200
    assert body["error"] == {"code": -32600, "message": "Invalid Request"}


@pytest.mark.asyncio
async def test_unsupported_protocol_version_header_is_rejected() -> None:
    response = await Quater().handle(
        Request(
            method="POST",
            path="/mcp",
            headers={
                "content-type": "application/json",
                "mcp-protocol-version": "2099-01-01",
            },
            body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        )
    )

    assert response.status_code == 400
    assert response.body == b"Unsupported MCP protocol version"


@pytest.mark.asyncio
async def test_mcp_endpoint_rejects_non_post_methods() -> None:
    response = await Quater().handle(Request(method="GET", path="/mcp"))

    assert response.status_code == 405
    assert dict(response.headers)["allow"] == "POST"
    assert response.body == b"Method Not Allowed"


@pytest.mark.asyncio
async def test_malformed_json_rpc_input_returns_safe_protocol_errors() -> None:
    malformed_status, _, malformed_body = await raw_mcp_post(
        Quater(),
        b'{"jsonrpc":"2.0","id":1,"method":',
    )
    list_status, _, list_body = await raw_mcp_post(
        Quater(),
        b'["not", "a", "request"]',
    )
    bool_id_status, _, bool_id_body = await mcp_post(
        Quater(),
        {"jsonrpc": "2.0", "id": True, "method": "tools/list"},
    )

    assert malformed_status == 200
    assert malformed_body["error"] == {"code": -32700, "message": "Parse error"}
    assert "Traceback" not in json.dumps(malformed_body)

    assert list_status == 200
    assert list_body["error"] == {"code": -32600, "message": "Invalid Request"}

    assert bool_id_status == 200
    assert bool_id_body["error"] == {"code": -32600, "message": "Invalid Request"}
    assert bool_id_body["id"] is None


@pytest.mark.asyncio
async def test_unknown_notifications_are_accepted_without_executing_anything() -> None:
    status, body_bytes, body = await mcp_post(
        Quater(),
        {"jsonrpc": "2.0", "method": "notifications/unknown"},
    )

    assert status == 202
    assert body_bytes == b""
    assert body == {}


@pytest.mark.asyncio
async def test_tools_call_rejects_invalid_params_without_handler_execution() -> None:
    calls = 0
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"id": id}

    invalid_payloads: list[dict[str, object]] = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": 7, "arguments": {"id": 1}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_user", "arguments": []},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_user",
                "arguments": {"id": 1},
                "_meta": {"approvalToken": " "},
            },
        },
    ]

    for payload in invalid_payloads:
        status, _, body = await mcp_post(
            app,
            payload,
            headers={
                "authorization": "Bearer mcp",
                "content-type": "application/json",
            },
        )
        assert status == 200
        assert require_object(body["error"])["code"] == -32602

    assert calls == 0
