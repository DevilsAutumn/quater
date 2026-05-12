from __future__ import annotations

from typing import Any, assert_type

from quater import (
    AuthContext,
    AuthRequest,
    MCPTestClient,
    Quater,
    TestClient,
    TestResponse,
)


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer token":
        return None
    return AuthContext(subject="test")


app = Quater(mcp_auth=authenticate, mcp_allowed_origins=["https://client.example"])


@app.get("/health", tool=True, description="Check application health.")
async def health() -> dict[str, bool]:
    return {"ok": True}


async def client_contract() -> None:
    async with TestClient(app) as client:
        response = await client.get(
            "/health",
            params={"page": 1, "tag": ["blue", "green"]},
            headers={"x-test": "yes"},
        )
        pair_response = await client.get(
            "/health",
            params=[("page", "1"), ("tag", "blue")],
        )
        payload = response.json()
        mcp_response = await client.mcp.tools_call(
            "health",
            {},
            token="token",
            origin="https://client.example",
        )

    assert_type(response, TestResponse)
    assert_type(response.status_code, int)
    assert_type(response.headers["content-type"], str)
    assert_type(response.text, str)
    assert_type(response.body, bytes)
    assert_type(response.is_success, bool)
    assert_type(client.mcp, MCPTestClient)
    assert_type(pair_response, TestResponse)
    assert_type(payload, Any)
    assert_type(mcp_response, TestResponse)
