from __future__ import annotations

import json

import pytest

from quater import AccessLogEvent, AuthContext, AuthRequest, Quater, Request, TestClient
from quater.protocol.actions import ACTIONS_RPC_PATH
from quater.typing import RequestContext


async def allow_mcp(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="mcp")


async def allow_cli(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="cli")


@pytest.mark.asyncio
async def test_request_id_reaches_response_handler_and_access_log() -> None:
    events: list[AccessLogEvent] = []

    async def log_access(event: AccessLogEvent) -> None:
        events.append(event)

    app = Quater(access_logger=log_access)

    @app.get("/items/{id:int}")
    async def get_item(id: int, request: Request) -> dict[str, object]:
        return {
            "id": id,
            "request_id": request.context.request_id,
            "source": request.context.source,
            "entrypoint": request.context.entrypoint,
        }

    async with TestClient(app) as client:
        response = await client.get(
            "/items/7?token=secret",
            headers={"x-request-id": "req-123"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-123"
    assert response.json() == {
        "id": 7,
        "request_id": "req-123",
        "source": "api",
        "entrypoint": "server",
    }
    assert len(events) == 1
    assert events[0].request_id == "req-123"
    assert events[0].source == "api"
    assert events[0].entrypoint == "server"
    assert events[0].path == "/items/7"
    assert events[0].status_code == 200
    assert "token" not in events[0].to_dict()


@pytest.mark.asyncio
async def test_invalid_context_request_id_is_not_echoed_to_response_headers() -> None:
    app = Quater()

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/ok",
            context=RequestContext(request_id="bad\r\nx-injected: yes"),
        )
    )

    assert response.status_code == 200
    request_id = dict(response.headers)["x-request-id"]
    assert request_id != "bad\r\nx-injected: yes"
    assert "\r" not in request_id
    assert "\n" not in request_id


@pytest.mark.asyncio
async def test_invalid_incoming_request_id_is_replaced_before_logging() -> None:
    events: list[AccessLogEvent] = []

    async def log_access(event: AccessLogEvent) -> None:
        events.append(event)

    app = Quater(access_logger=log_access)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        response = await client.get(
            "/ok",
            headers={"x-request-id": "bad value"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value"
    assert events[0].request_id == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_disabled_request_id_response_header_keeps_log_id() -> None:
    events: list[AccessLogEvent] = []

    async def log_access(event: AccessLogEvent) -> None:
        events.append(event)

    app = Quater(access_logger=log_access, request_id_header=None)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        response = await client.get("/ok", headers={"x-request-id": "req-123"})

    assert response.status_code == 200
    assert "x-request-id" not in response.headers
    assert len(events) == 1
    assert events[0].request_id
    assert events[0].request_id != "req-123"


@pytest.mark.asyncio
async def test_access_logger_failures_do_not_replace_the_response() -> None:
    async def broken_logger(event: AccessLogEvent) -> None:
        raise RuntimeError("logging backend is unavailable")

    app = Quater(access_logger=broken_logger)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        response = await client.get("/ok")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_mcp_tool_call_keeps_mcp_source_tool_name_and_request_id() -> None:
    events: list[AccessLogEvent] = []

    async def log_access(event: AccessLogEvent) -> None:
        events.append(event)

    app = Quater(mcp_auth=allow_mcp, access_logger=log_access)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        return {
            "id": id,
            "source": request.context.source,
            "entrypoint": request.context.entrypoint,
            "request_id": request.context.request_id,
            "tool": request.context.tool_name,
            "action": request.context.action_name,
        }

    async with TestClient(app) as client:
        response = await client.mcp.tools_call(
            "get_user",
            {"id": 7},
            token="mcp-token",
            headers={"x-request-id": "mcp-req-1"},
        )

    assert response.status_code == 200
    content = response.json()["result"]["content"]
    payload = json.loads(content[0]["text"])
    assert payload == {
        "id": 7,
        "source": "mcp",
        "entrypoint": "server",
        "request_id": "mcp-req-1",
        "tool": "get_user",
        "action": "get_user",
    }
    assert events[0].request_id == "mcp-req-1"
    assert events[0].source == "mcp"
    assert events[0].entrypoint == "server"
    assert events[0].tool_name == "get_user"
    assert events[0].action_name == "get_user"


@pytest.mark.asyncio
async def test_remote_cli_action_keeps_context_and_request_id() -> None:
    events: list[AccessLogEvent] = []

    async def log_access(event: AccessLogEvent) -> None:
        events.append(event)

    app = Quater(cli_auth=allow_cli, access_logger=log_access)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        return {
            "id": id,
            "source": request.context.source,
            "entrypoint": request.context.entrypoint,
            "request_id": request.context.request_id,
            "action": request.context.action_name,
        }

    async with TestClient(app) as client:
        response = await client.post(
            ACTIONS_RPC_PATH,
            headers={"authorization": "Bearer cli", "x-request-id": "cli-req-1"},
            json={"action": "get_user", "arguments": {"id": 7}},
        )

    assert response.status_code == 200
    assert response.json()["body"] == {
        "id": 7,
        "source": "cli",
        "entrypoint": "server",
        "request_id": "cli-req-1",
        "action": "get_user",
    }
    assert events[0].request_id == "cli-req-1"
    assert events[0].source == "cli"
    assert events[0].entrypoint == "server"
    assert events[0].action_name == "get_user"
