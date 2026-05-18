from __future__ import annotations

from typing import cast

import pytest

from quater import AuthContext, AuthRequest, Quater, Request, TestClient

from .helpers import (
    INTERNAL_PATH_MARKER,
    SECRET_MARKER,
    decoded_object,
    decoded_test_object,
    deny_auth,
    exploding_auth,
    remote_action_call,
    route_token_auth,
    surface_headers,
    surface_token_auth,
)


@pytest.mark.asyncio
async def test_malformed_auth_result_denies_instead_of_authenticating() -> None:
    calls = 0

    async def malformed_auth(_ctx: AuthRequest) -> AuthContext | None:
        return cast(AuthContext, {"subject": "not-an-auth-context"})

    app = Quater()

    @app.get("/private", auth=malformed_auth)
    async def private() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/private"))

    assert response.status_code == 401
    assert response.body == b"Unauthorized"
    assert calls == 0


@pytest.mark.asyncio
async def test_auth_denial_and_exceptions_never_call_protected_handler() -> None:
    denied_calls = 0
    exploding_calls = 0
    app = Quater()

    @app.get("/denied", auth=deny_auth)
    async def denied() -> dict[str, bool]:
        nonlocal denied_calls
        denied_calls += 1
        return {"ok": True}

    @app.get("/exploding", auth=exploding_auth)
    async def exploding() -> dict[str, bool]:
        nonlocal exploding_calls
        exploding_calls += 1
        return {"ok": True}

    denied_response = await app.handle(Request(method="GET", path="/denied"))
    exploding_response = await app.handle(Request(method="GET", path="/exploding"))

    assert denied_response.status_code == 401
    assert denied_response.body == b"Unauthorized"
    assert denied_calls == 0

    assert exploding_response.status_code == 500
    assert exploding_response.body == b"Internal Server Error"
    assert SECRET_MARKER.encode() not in exploding_response.body
    assert INTERNAL_PATH_MARKER.encode() not in exploding_response.body
    assert exploding_calls == 0


@pytest.mark.asyncio
async def test_same_route_auth_gate_protects_http_mcp_and_remote_cli() -> None:
    calls: list[str] = []
    app = Quater(mcp_auth=surface_token_auth, cli_auth=surface_token_auth)

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        auth=route_token_auth,
        description="Read one order.",
    )
    async def get_order(order_id: str, request: Request) -> dict[str, object]:
        calls.append(request.context.source)
        assert request.auth is not None
        return {
            "order_id": order_id,
            "subject": request.auth.subject,
            "source": request.context.source,
        }

    http_denied = await app.handle(
        Request(
            method="GET",
            path="/orders/ord_1001",
            headers=surface_headers(route=False),
        )
    )
    assert http_denied.status_code == 401

    async with TestClient(app) as client:
        mcp_denied = await client.mcp.tools_call(
            "get_order",
            {"order_id": "ord_1001"},
            token="surface-token",
        )
    mcp_denied_body = decoded_test_object(mcp_denied)
    assert mcp_denied.status_code == 200
    assert mcp_denied_body["result"] == {
        "content": [{"type": "text", "text": "Unauthorized"}],
        "isError": True,
    }

    cli_denied = await remote_action_call(
        app,
        {"action": "get_order", "arguments": {"order_id": "ord_1001"}},
        headers=surface_headers(route=False),
    )
    assert cli_denied.status_code == 401
    assert decoded_object(cli_denied.body)["error"] == {
        "code": "http_error",
        "message": "Unauthorized",
    }
    assert calls == []

    http_allowed = await app.handle(
        Request(
            method="GET",
            path="/orders/ord_1001",
            headers=surface_headers(route=True),
        )
    )
    async with TestClient(app) as client:
        mcp_allowed = await client.mcp.tools_call(
            "get_order",
            {"order_id": "ord_1001"},
            token="surface-token",
            headers={"x-route-auth": "route-token"},
        )
    cli_allowed = await remote_action_call(
        app,
        {"action": "get_order", "arguments": {"order_id": "ord_1001"}},
        headers=surface_headers(route=True),
    )

    assert http_allowed.status_code == 200
    assert b'"source":"api"' in http_allowed.body

    mcp_allowed_body = decoded_test_object(mcp_allowed)
    assert mcp_allowed_body["result"] == {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"order_id":"ord_1001","subject":"route-user","source":"mcp"}'
                ),
            }
        ],
        "isError": False,
    }

    cli_allowed_body = decoded_object(cli_allowed.body)
    assert cli_allowed.status_code == 200
    assert cli_allowed_body["body"] == {
        "order_id": "ord_1001",
        "subject": "route-user",
        "source": "cli",
    }
    assert calls == ["api", "mcp", "cli"]


@pytest.mark.asyncio
async def test_surface_auth_protects_mcp_and_cli_discovery() -> None:
    app = Quater(mcp_auth=surface_token_auth, cli_auth=surface_token_auth)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/orders/{order_id}", tool=True, cli=True, description="Read one order.")
    async def get_order(order_id: str) -> dict[str, str]:
        return {"order_id": order_id}

    async with TestClient(app) as client:
        mcp_denied = await client.mcp.tools_list()
        mcp_allowed = await client.mcp.tools_list(token="surface-token")
    cli_denied = await remote_action_call(
        app,
        {"action": "get_order", "arguments": {"order_id": "ord_1001"}},
    )

    assert mcp_denied.status_code == 401
    assert b"get_order" not in mcp_denied.body
    assert mcp_allowed.status_code == 200
    assert b"health" not in mcp_allowed.body
    assert b"get_order" in mcp_allowed.body

    assert cli_denied.status_code == 401
    assert b"get_order" not in cli_denied.body
