from __future__ import annotations

import importlib
import json
import pathlib
import sys
from collections.abc import Mapping
from typing import Protocol, cast

import pytest

from quater import Quater, Request, Response


class ExampleModule(Protocol):
    app: Quater


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

asgi_compat = cast(ExampleModule, importlib.import_module("examples.asgi_compat"))
auth_and_mcp = cast(ExampleModule, importlib.import_module("examples.auth_and_mcp"))
basic_app = cast(ExampleModule, importlib.import_module("examples.basic_app"))
wsgi_compat = cast(ExampleModule, importlib.import_module("examples.wsgi_compat"))


def require_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def require_object_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


@pytest.mark.asyncio
async def test_basic_example_routes_run_through_core_app() -> None:
    response = await basic_app.app.handle(Request(method="GET", path="/health"))

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'


@pytest.mark.asyncio
async def test_basic_example_echo_route_reads_json_body() -> None:
    response = await basic_app.app.handle(
        Request(
            method="POST",
            path="/echo",
            headers={"content-type": "application/json"},
            body=b'{"message":"hello"}',
        )
    )

    assert response.status_code == 200
    assert response.body == b'{"received":{"message":"hello"}}'


def test_example_modules_expose_adapter_targets() -> None:
    assert callable(basic_app.app.rsgi)
    assert callable(asgi_compat.app.asgi)
    assert callable(wsgi_compat.app.wsgi)


@pytest.mark.asyncio
async def test_auth_example_protects_normal_http_route() -> None:
    denied = await auth_and_mcp.app.handle(Request(method="GET", path="/profile"))
    allowed = await auth_and_mcp.app.handle(
        Request(
            method="GET",
            path="/profile",
            headers={"authorization": "Bearer demo-token"},
        )
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.body == b'{"subject":"demo-user","source":"api"}'


@pytest.mark.asyncio
async def test_auth_example_exposes_only_tool_route_to_mcp() -> None:
    response = await _mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        }
    )
    body = require_object(json.loads(response.body))
    result = require_object(body["result"])
    tools = require_object_list(result["tools"])

    assert response.status_code == 200
    assert [tool["name"] for tool in tools] == ["get_user"]


@pytest.mark.asyncio
async def test_auth_example_tool_call_uses_mcp_context() -> None:
    response = await _mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_user", "arguments": {"id": 7}},
        }
    )
    body = require_object(json.loads(response.body))
    result = require_object(body["result"])
    content = require_object_list(result["content"])

    assert response.status_code == 200
    assert content[0]["text"] == (
        '{"id":7,"subject":"demo-user","source":"mcp","tool":"get_user"}'
    )


async def _mcp_request(payload: Mapping[str, object]) -> Response:
    return await auth_and_mcp.app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={
                "authorization": "Bearer demo-token",
                "content-type": "application/json",
                "origin": "http://localhost:3000",
            },
            body=json.dumps(payload).encode("utf-8"),
        )
    )
