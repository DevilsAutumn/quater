from __future__ import annotations

import msgspec
import pytest

from quater import Quater, Request
from quater.typing import AuthContext, AuthRequest


@pytest.mark.asyncio
async def test_mcp_docs_are_generated_by_default() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return AuthContext(subject="user_1")

    app = Quater(mcp_auth=authenticate)

    @app.get(
        "/users/{id:int}",
        tool=True,
        auth=authenticate,
        description="Fetch <one> user.",
    )
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(Request(method="GET", path="/mcp/docs"))
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert dict(response.headers)["content-type"] == "text/html; charset=utf-8"
    assert dict(response.headers)["content-security-policy"].startswith(
        "default-src 'none'"
    )
    assert "get_user" in body
    assert "Fetch &lt;one&gt; user." in body
    assert "HTTP route: <code>GET /users/{id:int}</code>" in body
    assert "Auth: required" in body
    assert '<h3>Input Schema</h3><pre>{\n  "type": "object"' in body
    assert '<h3>Output Schema</h3><pre>{\n  "type": "object"' in body
    assert '<h3>Example Request</h3><pre>{\n  "jsonrpc": "2.0"' in body
    assert '"method": "tools/call"' in body


@pytest.mark.asyncio
async def test_mcp_docs_path_is_configurable() -> None:
    app = Quater(mcp_docs_path="/agent-tools")

    response = await app.handle(Request(method="GET", path="/agent-tools"))

    assert response.status_code == 200
    assert "No MCP tools are registered yet." in response.body.decode("utf-8")


@pytest.mark.asyncio
async def test_mcp_docs_can_be_disabled() -> None:
    app = Quater(mcp_docs_path=None)

    response = await app.handle(Request(method="GET", path="/mcp/docs"))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mcp_docs_use_mcp_auth_when_tools_are_registered() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer docs":
            return None
        return AuthContext(subject="docs-user")

    app = Quater(mcp_auth=authenticate)

    @app.get("/private", tool=True, description="Read private data.")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    denied = await app.handle(Request(method="GET", path="/mcp/docs"))
    allowed = await app.handle(
        Request(
            method="GET",
            path="/mcp/docs",
            headers={"authorization": "Bearer docs"},
        )
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200


class BatchPayload(msgspec.Struct):
    ids: list[int]


@pytest.mark.asyncio
async def test_mcp_docs_generate_examples_for_required_argument_types() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(mcp_auth=authenticate)

    @app.post("/batches/{bucket}", tool=True, description="Process a batch.")
    async def process_batch(
        bucket: str,
        threshold: float,
        active: bool,
        payload: BatchPayload,
    ) -> dict[str, object]:
        return {
            "bucket": bucket,
            "threshold": threshold,
            "active": active,
            "ids": payload.ids,
        }

    response = await app.handle(
        Request(
            method="GET",
            path="/mcp/docs",
            headers={"authorization": "Bearer mcp"},
        )
    )
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert '"bucket": "string"' in body
    assert '"threshold": 12.3' in body
    assert '"active": true' in body
    assert '"payload": {}' in body
    assert '"method": "tools/call"' in body
