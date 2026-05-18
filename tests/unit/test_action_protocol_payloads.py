from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import JSONResponse, Response, StreamResponse
from quater.protocol.actions import MAX_ACTION_RESPONSE_BYTES, response_payload


async def stream_chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_action_response_payload_preserves_json_body_shape() -> None:
    response = JSONResponse({"order_id": "ord_1001", "ok": True})

    assert await response_payload(response) == {
        "ok": True,
        "status_code": 200,
        "body": {"order_id": "ord_1001", "ok": True},
    }


@pytest.mark.asyncio
async def test_action_response_payload_falls_back_to_text_for_non_json() -> None:
    response = Response(b"accepted", content_type="text/plain; charset=utf-8")

    assert await response_payload(response) == {
        "ok": True,
        "status_code": 200,
        "body": "accepted",
    }


@pytest.mark.asyncio
async def test_action_response_payload_decodes_malformed_json_as_text() -> None:
    response = Response(b"{not-json", content_type="application/json")

    assert await response_payload(response) == {
        "ok": True,
        "status_code": 200,
        "body": "{not-json",
    }


@pytest.mark.asyncio
async def test_action_response_payload_supports_streaming_responses() -> None:
    response = StreamResponse(
        stream_chunks(b'{"order_id":"', b'ord_1001"}'),
        content_type="application/json",
    )

    assert await response_payload(response) == {
        "ok": True,
        "status_code": 200,
        "body": {"order_id": "ord_1001"},
    }


@pytest.mark.asyncio
async def test_action_response_payload_rejects_oversized_plain_responses() -> None:
    response = Response(b"x" * (MAX_ACTION_RESPONSE_BYTES + 1))

    with pytest.raises(ValueError, match="exceeded 1 MiB"):
        await response_payload(response)


@pytest.mark.asyncio
async def test_action_response_payload_rejects_oversized_streaming_responses() -> None:
    response = StreamResponse(
        stream_chunks(b"x" * MAX_ACTION_RESPONSE_BYTES, b"x"),
    )

    with pytest.raises(ValueError, match="exceeded 1 MiB"):
        await response_payload(response)
