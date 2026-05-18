from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import Quater, Request, Resource, TestClient

from .helpers import (
    allow_auth,
    decoded_object,
    decoded_test_object,
    remote_action_call,
    remote_action_manifest,
    surface_headers,
    surface_token_auth,
)


class PrivateSession:
    def __init__(self, label: str) -> None:
        self.label = label


@pytest.mark.asyncio
async def test_http_routes_are_not_exposed_to_mcp_or_cli_without_opt_in() -> None:
    app = Quater(mcp_auth=surface_token_auth, cli_auth=surface_token_auth)

    @app.get("/internal")
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/tools/{name}", tool=True, description="Read one tool-backed value.")
    async def tool_only(name: str) -> dict[str, str]:
        return {"name": name}

    @app.get("/actions/{name}", cli=True, description="Read one CLI-backed value.")
    async def cli_only(name: str) -> dict[str, str]:
        return {"name": name}

    async with TestClient(app) as client:
        tools_response = await client.mcp.tools_list(token="surface-token")
        internal_call = await client.mcp.tools_call(
            "internal",
            {},
            token="surface-token",
        )
    manifest_response = await remote_action_manifest(
        app,
        headers=surface_headers(),
    )
    cli_internal_call = await remote_action_call(
        app,
        {"action": "internal", "arguments": {}},
        headers=surface_headers(),
    )

    tools_body = decoded_test_object(tools_response)
    tools = tools_body["result"]
    assert isinstance(tools, dict)
    assert tools["tools"] == [
        {
            "name": "tool_only",
            "description": "Read one tool-backed value.",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "additionalProperties": False,
                "required": ["name"],
            },
        }
    ]
    assert decoded_test_object(internal_call)["error"] == {
        "code": -32602,
        "message": "Unknown tool",
    }

    manifest = decoded_object(manifest_response.body)
    actions = manifest["actions"]
    assert isinstance(actions, list)
    assert len(actions) == 1
    assert actions[0]["name"] == "cli_only"

    assert cli_internal_call.status_code == 404
    assert decoded_object(cli_internal_call.body)["error"] == {
        "code": "unknown_action",
        "message": "Unknown action",
    }


@pytest.mark.asyncio
async def test_external_schemas_do_not_expose_request_or_resource_parameters() -> None:
    async def session_provider() -> AsyncIterator[PrivateSession]:
        yield PrivateSession("primary")

    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        inject={"session": Resource(session_provider)},
        description="Read one order.",
    )
    async def get_order(
        order_id: str,
        request: Request,
        session: PrivateSession,
        include_events: bool = False,
    ) -> dict[str, object]:
        return {
            "order_id": order_id,
            "session": session.label,
            "source": request.context.source,
            "include_events": include_events,
        }

    async with TestClient(app) as client:
        tools_response = await client.mcp.tools_list(token="anything")
    manifest_response = await remote_action_manifest(
        app,
        headers={"authorization": "Bearer anything"},
    )

    tool = decoded_test_object(tools_response)["result"]
    assert isinstance(tool, dict)
    tool_list = tool["tools"]
    assert isinstance(tool_list, list)
    input_schema = tool_list[0]["inputSchema"]
    assert input_schema == {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "include_events": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
        "required": ["order_id"],
    }

    manifest = decoded_object(manifest_response.body)
    actions = manifest["actions"]
    assert isinstance(actions, list)
    assert actions[0]["input_schema"] == input_schema


@pytest.mark.asyncio
async def test_action_argument_overposting_is_rejected_before_handler_runs() -> None:
    calls = 0
    app = Quater(cli_auth=surface_token_auth)

    @app.get("/orders/{order_id}", cli=True, description="Read one order.")
    async def get_order(order_id: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"order_id": order_id}

    response = await remote_action_call(
        app,
        {
            "action": "get_order",
            "arguments": {
                "order_id": "ord_1001",
                "request": "fake-request",
                "session": "fake-session",
            },
        },
        headers=surface_headers(),
    )

    assert response.status_code == 400
    assert decoded_object(response.body)["error"] == {
        "code": "bad_request",
        "message": "Unknown action argument: request",
    }
    assert calls == 0
