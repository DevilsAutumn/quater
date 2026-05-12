from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

import msgspec
import pytest

from quater import AuthContext, AuthRequest, HTTPError, Quater, Request, Response
from quater.tools.mcp import MAX_TOOL_RESPONSE_BYTES
from quater.typing import ApprovalRequest


async def allow_mcp_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="mcp")


class CreateUser(msgspec.Struct):
    name: str
    age: int


async def mcp_call(
    app: Quater,
    *,
    name: str,
    arguments: dict[str, object],
    meta: dict[str, object] | None = None,
    request_id: int = 1,
) -> tuple[int, dict[str, object]]:
    params: dict[str, object] = {"name": name, "arguments": arguments}
    if meta is not None:
        params["_meta"] = meta
    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={
                "authorization": "Bearer mcp",
                "content-type": "application/json",
            },
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": params,
                }
            ).encode("utf-8"),
        )
    )
    return response.status_code, json.loads(response.body)


def require_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def require_object_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


@pytest.mark.asyncio
async def test_tools_call_invokes_handler_with_tool_request_context() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        assert request.context.source == "tool"
        assert request.context.tool_name == "get_user"
        assert request.context.action_name == "get_user"
        assert request.auth is not None
        return {
            "id": id,
            "source": request.context.source,
            "action": request.context.action_name,
            "subject": request.auth.subject,
        }

    status, body = await mcp_call(app, name="get_user", arguments={"id": 7})

    assert status == 200
    assert body["result"] == {
        "content": [
            {
                "type": "text",
                "text": '{"id":7,"source":"tool","action":"get_user","subject":"mcp"}',
            },
        ],
        "isError": False,
    }


@pytest.mark.asyncio
async def test_tools_call_reuses_cached_json_rpc_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Quater(mcp_auth=allow_mcp_auth)
    original_decode = cast(Callable[..., object], msgspec.json.decode)
    decode_calls = 0

    def decode_json(*args: object, **kwargs: object) -> object:
        nonlocal decode_calls
        decode_calls += 1
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(msgspec.json, "decode", decode_json)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, object]:
        return {"id": id}

    status, body = await mcp_call(app, name="get_user", arguments={"id": 7})

    assert status == 200
    result = require_object(body["result"])
    assert result["isError"] is False
    assert decode_calls == 1


@pytest.mark.asyncio
async def test_normal_api_call_keeps_api_request_context() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        return {"id": id, "source": request.context.source}

    response = await app.handle(Request(method="GET", path="/users/7"))

    assert response.body == b'{"id":7,"source":"api"}'


@pytest.mark.asyncio
async def test_tools_call_escapes_rendered_request_path_parameters() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/files/{name}", tool=True, description="Fetch one file.")
    async def get_file(name: str, request: Request) -> dict[str, str]:
        return {"name": name, "path": request.path}

    status, body = await mcp_call(
        app,
        name="get_file",
        arguments={"name": "reports/2026 draft"},
    )

    assert status == 200
    result = require_object(body["result"])
    content = require_object_list(result["content"])
    assert (
        content[0]["text"]
        == '{"name":"reports/2026 draft","path":"/files/reports%2F2026%20draft"}'
    )
    assert result["isError"] is False


@pytest.mark.asyncio
async def test_tools_call_binds_body_model_from_arguments() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.post("/users", tool=True, description="Create one user.")
    async def create_user(user: CreateUser) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    status, body = await mcp_call(
        app,
        name="create_user",
        arguments={"user": {"name": "Ada", "age": 37}},
    )

    assert status == 200
    result = require_object(body["result"])
    content = require_object_list(result["content"])
    assert content[0]["text"] == '{"name":"Ada","age":37}'
    assert result["isError"] is False


@pytest.mark.asyncio
async def test_unknown_tool_returns_json_rpc_error() -> None:
    status, body = await mcp_call(
        Quater(),
        name="missing",
        arguments={},
    )

    assert status == 200
    assert body["error"] == {"code": -32602, "message": "Unknown tool"}


@pytest.mark.asyncio
async def test_invalid_tool_arguments_do_not_call_handler() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)
    calls = 0

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"id": id}

    status, body = await mcp_call(app, name="get_user", arguments={"id": "broken"})

    assert status == 200
    assert body["error"] == {"code": -32602, "message": "Invalid path argument: id"}
    assert calls == 0


@pytest.mark.asyncio
async def test_handler_error_becomes_tool_result_error() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/boom", tool=True, description="Raise a handler error.")
    async def boom() -> dict[str, bool]:
        raise RuntimeError("database token leaked")

    status, body = await mcp_call(app, name="boom", arguments={})

    assert status == 200
    assert body["result"] == {
        "content": [{"type": "text", "text": "Tool call failed"}],
        "isError": True,
    }


@pytest.mark.asyncio
async def test_handler_http_error_stays_json_rpc_tool_result() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/missing-resource", tool=True, description="Return an HTTP error.")
    async def missing_resource() -> dict[str, bool]:
        raise HTTPError("Resource not found", status_code=404)

    status, body = await mcp_call(app, name="missing_resource", arguments={})

    assert status == 200
    assert body["result"] == {
        "content": [{"type": "text", "text": "Resource not found"}],
        "isError": True,
    }


@pytest.mark.asyncio
async def test_oversized_tool_response_becomes_tool_result_error() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/large", tool=True, description="Return a large payload.")
    async def large() -> Response:
        return Response(b"x" * (MAX_TOOL_RESPONSE_BYTES + 1))

    status, body = await mcp_call(app, name="large", arguments={})

    assert status == 200
    assert body["result"] == {
        "content": [{"type": "text", "text": "Tool response too large"}],
        "isError": True,
    }


@pytest.mark.asyncio
async def test_approval_required_tool_call_requires_token() -> None:
    approval_calls = 0
    handler_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        nonlocal approval_calls
        approval_calls += 1
        return True

    app = Quater(mcp_auth=allow_mcp_auth, action_approval=approve)

    @app.post(
        "/invoices/{id:int}/paid",
        tool=True,
        needs_approval=True,
        description="Mark an invoice as paid.",
    )
    async def mark_paid(id: int) -> dict[str, int]:
        nonlocal handler_calls
        handler_calls += 1
        return {"id": id}

    status, body = await mcp_call(app, name="mark_paid", arguments={"id": 7})

    assert status == 200
    error = require_object(body["error"])
    assert error["code"] == -32001
    assert error["message"] == "Approval required"
    error_data = require_object(error["data"])
    assert error_data["code"] == "approval_required"
    assert error_data["action"] == "mark_paid"
    assert str(error_data["arguments_hash"]).startswith("sha256:")
    assert approval_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_normal_api_call_to_approval_required_tool_uses_http_path() -> None:
    async def approve(ctx: ApprovalRequest) -> bool:
        return False

    app = Quater(mcp_auth=allow_mcp_auth, action_approval=approve)

    @app.post(
        "/invoices/{id:int}/paid",
        tool=True,
        needs_approval=True,
        description="Mark an invoice as paid.",
    )
    async def mark_paid(id: int, request: Request) -> dict[str, object]:
        return {"id": id, "source": request.context.source}

    response = await app.handle(Request(method="POST", path="/invoices/7/paid"))

    assert response.status_code == 200
    assert response.body == b'{"id":7,"source":"api"}'


@pytest.mark.asyncio
async def test_approval_required_tool_call_rejects_bad_token() -> None:
    seen: list[ApprovalRequest] = []
    handler_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        seen.append(ctx)
        return False

    app = Quater(mcp_auth=allow_mcp_auth, action_approval=approve)

    @app.post(
        "/invoices/{id:int}/paid",
        tool=True,
        needs_approval=True,
        description="Mark an invoice as paid.",
    )
    async def mark_paid(id: int) -> dict[str, int]:
        nonlocal handler_calls
        handler_calls += 1
        return {"id": id}

    status, body = await mcp_call(
        app,
        name="mark_paid",
        arguments={"id": 7},
        meta={"approvalToken": "bad"},
    )

    assert status == 200
    error = require_object(body["error"])
    assert error["code"] == -32002
    assert error["message"] == "Approval denied"
    assert len(seen) == 1
    assert seen[0].action == "mark_paid"
    assert seen[0].token == "bad"
    assert seen[0].auth is not None
    assert seen[0].auth.subject == "mcp"
    assert seen[0].context.source == "tool"
    assert seen[0].context.tool_name == "mark_paid"
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_approval_required_tool_call_runs_after_valid_token() -> None:
    seen_hashes: list[str] = []

    async def approve(ctx: ApprovalRequest) -> bool:
        seen_hashes.append(ctx.arguments_hash)
        return ctx.token == "approved"

    app = Quater(mcp_auth=allow_mcp_auth, action_approval=approve)

    @app.post(
        "/invoices/{id:int}/paid",
        tool=True,
        needs_approval=True,
        description="Mark an invoice as paid.",
    )
    async def mark_paid(id: int) -> dict[str, int]:
        return {"id": id}

    status, body = await mcp_call(
        app,
        name="mark_paid",
        arguments={"id": 7},
        meta={"approvalToken": "approved"},
    )

    assert status == 200
    result = require_object(body["result"])
    content = require_object_list(result["content"])
    assert content[0]["text"] == '{"id":7}'
    assert result["isError"] is False
    assert len(seen_hashes) == 1
    assert seen_hashes[0].startswith("sha256:")


@pytest.mark.asyncio
async def test_invalid_approval_token_shape_returns_invalid_params() -> None:
    async def approve(ctx: ApprovalRequest) -> bool:
        return True

    app = Quater(mcp_auth=allow_mcp_auth, action_approval=approve)

    @app.post(
        "/invoices/{id:int}/paid",
        tool=True,
        needs_approval=True,
        description="Mark an invoice as paid.",
    )
    async def mark_paid(id: int) -> dict[str, int]:
        return {"id": id}

    status, body = await mcp_call(
        app,
        name="mark_paid",
        arguments={"id": 7},
        meta={"approvalToken": ""},
    )

    assert status == 200
    assert body["error"] == {"code": -32602, "message": "Invalid approval token"}
