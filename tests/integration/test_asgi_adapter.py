from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

import pytest

from quater import Quater, Request, StreamResponse
from quater.adapters.asgi import ASGIAdapter, ASGIMessage


async def call_asgi(
    adapter: ASGIAdapter,
    scope: dict[str, object],
    messages: list[ASGIMessage],
) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []

    async def receive() -> ASGIMessage:
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        sent.append(dict(message))

    await adapter(scope, receive, send)
    return sent


def response_body(messages: list[dict[str, object]]) -> bytes:
    return b"".join(
        cast(bytes, message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )


def response_headers(messages: list[dict[str, object]]) -> dict[str, str]:
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    return {
        name.decode("latin-1"): value.decode("latin-1")
        for name, value in cast(list[tuple[bytes, bytes]], start["headers"])
    }


@pytest.mark.asyncio
async def test_asgi_multiple_body_chunks_reach_handler_without_loss() -> None:
    app = Quater()

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "POST",
            "path": "/echo",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        [
            {"type": "http.request", "body": b"hello ", "more_body": True},
            {"type": "http.request", "body": b"world", "more_body": False},
        ],
    )

    assert sent[0]["status"] == 200
    assert response_body(sent) == b"hello world"


@pytest.mark.asyncio
async def test_asgi_body_limit_stops_reading_oversized_chunked_body() -> None:
    app = Quater(max_body_size=4)
    receive_calls = 0
    messages: list[ASGIMessage] = [
        {"type": "http.request", "body": b"12", "more_body": True},
        {"type": "http.request", "body": b"345", "more_body": True},
        {"type": "http.request", "body": b"ignored", "more_body": False},
    ]
    sent: list[dict[str, object]] = []

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    async def receive() -> ASGIMessage:
        nonlocal receive_calls
        receive_calls += 1
        return messages.pop(0)

    async def send(message: Mapping[str, Any]) -> None:
        sent.append(dict(message))

    await app.asgi(
        {
            "type": "http",
            "method": "POST",
            "path": "/echo",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        receive,
        send,
    )

    assert sent[0]["status"] == 413
    assert response_body(sent) == b"Payload Too Large"
    assert receive_calls == 2


@pytest.mark.asyncio
async def test_asgi_non_stream_response_uses_single_final_body_message() -> None:
    app = Quater()

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"hello": "world"}

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "GET",
            "path": "/hello",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    body_messages = [
        message for message in sent if message["type"] == "http.response.body"
    ]
    assert body_messages == [
        {
            "type": "http.response.body",
            "body": b'{"hello":"world"}',
            "more_body": False,
        }
    ]


@pytest.mark.asyncio
async def test_asgi_stream_response_uses_multiple_body_messages() -> None:
    app = Quater()

    async def chunks() -> AsyncIterator[bytes]:
        yield b"a"
        yield b"b"

    @app.get("/stream")
    async def stream() -> StreamResponse:
        return StreamResponse(chunks())

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "GET",
            "path": "/stream",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    body_messages = [
        message for message in sent if message["type"] == "http.response.body"
    ]
    assert [message["body"] for message in body_messages] == [b"a", b"b", b""]
    assert body_messages[-1]["more_body"] is False


@pytest.mark.asyncio
async def test_asgi_lifespan_runs_startup_and_shutdown_once() -> None:
    app = Quater()
    calls: list[str] = []

    @app.on_startup
    async def startup() -> None:
        calls.append("startup")

    @app.on_shutdown
    async def shutdown() -> None:
        calls.append("shutdown")

    sent = await call_asgi(
        app.asgi,
        {"type": "lifespan"},
        [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ],
    )

    assert calls == ["startup", "shutdown"]
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]


@pytest.mark.asyncio
async def test_asgi_websocket_scope_closes_without_entering_router() -> None:
    app = Quater()
    calls = 0

    @app.get("/ws")
    async def route() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    sent = await call_asgi(
        app.asgi,
        {"type": "websocket", "path": "/ws"},
        [],
    )

    assert calls == 0
    assert sent == [
        {
            "type": "websocket.close",
            "code": 1003,
            "reason": "WebSocket support is not enabled",
        }
    ]
