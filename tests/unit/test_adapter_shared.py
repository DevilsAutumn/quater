from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import Response, StreamResponse
from quater.adapters._shared import (
    as_latin1_header_bytes,
    collect_response_body,
    first_client_address,
    iter_response_body,
    response_headers,
    response_status,
)


async def streaming_chunks() -> AsyncIterator[bytes]:
    yield b""
    yield b"one"
    yield b""
    yield b"two"


def test_response_status_uses_standard_phrases_and_safe_unknown_fallback() -> None:
    assert response_status(200) == "200 OK"
    assert response_status(204) == "204 No Content"
    assert response_status(799) == "799 Unknown"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ((), None),
        ([], None),
        ([None], None),
        (("127.0.0.1", 53000), "127.0.0.1"),
        ("", None),
        ("api.example.com:443", "api.example.com"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("2001:db8::1", "2001:db8::1"),
        ("unix:/tmp/quater.sock", "unix:/tmp/quater.sock"),
    ],
)
def test_first_client_address_normalizes_common_server_shapes(
    value: object,
    expected: str | None,
) -> None:
    assert first_client_address(value) == expected


@pytest.mark.asyncio
async def test_response_body_iteration_skips_empty_chunks_without_adding_noise() -> (
    None
):
    assert [chunk async for chunk in iter_response_body(Response())] == []
    assert [chunk async for chunk in iter_response_body(Response(b"body"))] == [b"body"]

    stream = StreamResponse(streaming_chunks())

    assert [chunk async for chunk in iter_response_body(stream)] == [b"one", b"two"]


@pytest.mark.asyncio
async def test_collect_response_body_matches_adapter_chunk_collection() -> None:
    assert await collect_response_body(StreamResponse(streaming_chunks())) == [
        b"one",
        b"two",
    ]


def test_response_headers_and_latin1_header_encoding_are_adapter_ready() -> None:
    response = Response(
        b"ok",
        headers={"x-trace-id": "req-123"},
        content_type="text/plain",
    )

    assert response_headers(response) == [
        ("x-trace-id", "req-123"),
        ("content-type", "text/plain"),
    ]
    assert as_latin1_header_bytes(response.headers) == [
        (b"x-trace-id", b"req-123"),
        (b"content-type", b"text/plain"),
    ]
