from __future__ import annotations

import asyncio

import msgspec
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from quater import Quater, Request, TestClient

from .helpers import (
    INTERNAL_PATH_MARKER,
    SECRET_MARKER,
    decoded_test_object,
    surface_token_auth,
)


class CreateOrder(msgspec.Struct, forbid_unknown_fields=True):
    order_id: str
    quantity: int


@pytest.mark.asyncio
async def test_malformed_json_denies_handler_and_returns_safe_400() -> None:
    calls = 0
    app = Quater()

    @app.post("/orders")
    async def create_order(order: CreateOrder) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"order_id": order.order_id, "quantity": order.quantity}

    malformed = await app.handle(
        Request(
            method="POST",
            path="/orders",
            headers={"content-type": "application/json"},
            body=b'{"order_id": "ord_1001",',
        )
    )
    invalid_utf8 = await app.handle(
        Request(
            method="POST",
            path="/orders",
            headers={"content-type": "application/json"},
            body=b'{"order_id":"\xff","quantity":1}',
        )
    )
    wrong_type = await app.handle(
        Request(
            method="POST",
            path="/orders",
            headers={"content-type": "application/json"},
            body=b'{"order_id":"ord_1001","quantity":"many"}',
        )
    )
    overposted = await app.handle(
        Request(
            method="POST",
            path="/orders",
            headers={"content-type": "application/json"},
            body=(b'{"order_id":"ord_1001","quantity":1,"admin_override":true}'),
        )
    )

    assert malformed.status_code == 400
    assert malformed.body == b"Malformed JSON body"
    assert invalid_utf8.status_code == 400
    assert wrong_type.status_code == 400
    assert overposted.status_code == 400
    assert calls == 0


@pytest.mark.asyncio
async def test_json_body_parsing_is_annotation_driven_not_content_type_driven() -> None:
    app = Quater()

    @app.post("/orders")
    async def create_order(order: CreateOrder) -> dict[str, object]:
        return {"order_id": order.order_id, "quantity": order.quantity}

    response = await app.handle(
        Request(
            method="POST",
            path="/orders",
            headers={"content-type": "text/plain"},
            body=b'{"order_id":"ord_1001","quantity":2}',
        )
    )

    assert response.status_code == 200
    assert response.body == b'{"order_id":"ord_1001","quantity":2}'


@pytest.mark.asyncio
async def test_body_size_limit_fails_before_handler_reads_large_body() -> None:
    calls = 0
    app = Quater(max_body_size=8)

    @app.post("/orders")
    async def create_order(order: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return order

    response = await app.handle(
        Request(
            method="POST",
            path="/orders",
            headers={"content-length": "128"},
            body=b'{"order_id":"ord_1001"}',
        )
    )

    assert response.status_code == 413
    assert response.body == b"Payload Too Large"
    assert calls == 0


@pytest.mark.asyncio
async def test_unserializable_handler_result_fails_without_secret_leakage() -> None:
    class SecretCarrier:
        token = SECRET_MARKER

        def __repr__(self) -> str:
            return f"<SecretCarrier token={self.token}>"

    app = Quater()

    @app.get("/unsafe")
    async def unsafe() -> SecretCarrier:
        return SecretCarrier()

    response = await app.handle(Request(method="GET", path="/unsafe"))

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"
    assert SECRET_MARKER.encode() not in response.body
    assert b"SecretCarrier" not in response.body


@pytest.mark.asyncio
async def test_handler_exception_does_not_leak_secret_markers_in_production() -> None:
    app = Quater()

    @app.get("/boom")
    async def boom() -> dict[str, bool]:
        raise RuntimeError(f"{SECRET_MARKER} at {INTERNAL_PATH_MARKER}/app.py")

    response = await app.handle(Request(method="GET", path="/boom"))

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"
    assert SECRET_MARKER.encode() not in response.body
    assert INTERNAL_PATH_MARKER.encode() not in response.body


@pytest.mark.asyncio
async def test_mcp_tool_exception_returns_safe_tool_error() -> None:
    app = Quater(mcp_auth=surface_token_auth)

    @app.get("/boom", tool=True, description="Raise a production error.")
    async def boom() -> dict[str, bool]:
        raise RuntimeError(f"{SECRET_MARKER} at {INTERNAL_PATH_MARKER}/tool.py")

    async with TestClient(app) as client:
        response = await client.mcp.tools_call("boom", token="surface-token")

    body = decoded_test_object(response)
    assert response.status_code == 200
    assert body["result"] == {
        "content": [{"type": "text", "text": "Tool call failed"}],
        "isError": True,
    }
    assert SECRET_MARKER not in response.text
    assert INTERNAL_PATH_MARKER not in response.text


@given(query_string=st.binary(max_size=128))
@settings(max_examples=100)
def test_fuzzed_query_strings_never_return_internal_server_error(
    query_string: bytes,
) -> None:
    async def run_case() -> None:
        app = Quater()

        @app.get("/search")
        async def search(term: str = "") -> dict[str, str]:
            return {"term": term}

        response = await app.handle(
            Request(method="GET", path="/search", query_string=query_string)
        )

        assert response.status_code in {200, 400}
        assert response.body != b"Internal Server Error"

    asyncio.run(run_case())
