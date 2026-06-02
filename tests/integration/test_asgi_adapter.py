from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

import pytest

from quater import (
    AuthConfig,
    AuthContext,
    Quater,
    Request,
    Resource,
    Response,
    StreamResponse,
)
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


async def call_asgi_file_lookup(
    *,
    path: str,
    raw_path: bytes | None = None,
) -> tuple[int, bytes]:
    app = Quater()

    @app.get("/files/{name}")
    async def file(name: str) -> dict[str, str]:
        return {"name": name}

    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "scheme": "http",
        "query_string": b"",
        "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 5000),
    }
    if raw_path is not None:
        scope["raw_path"] = raw_path

    sent = await call_asgi(
        app.asgi,
        scope,
        [{"type": "http.request", "body": b"", "more_body": False}],
    )
    status = sent[0]["status"]
    assert isinstance(status, int)
    return status, response_body(sent)


@pytest.mark.asyncio
async def test_asgi_raw_path_decodes_non_ascii_path_segment() -> None:
    app = Quater()

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "GET",
            "path": "/items/caf\u00e9",
            "raw_path": b"/items/caf%C3%A9",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    assert sent[0]["status"] == 200
    assert response_body(sent) == b'{"item_id":"caf\xc3\xa9"}'


@pytest.mark.asyncio
async def test_asgi_raw_path_decodes_encoded_slash_before_matching() -> None:
    status, body = await call_asgi_file_lookup(
        path="/files/a/b",
        raw_path=b"/files/a%2Fb",
    )

    assert status == 404
    assert body == b"Not found: /files/a/b"


@pytest.mark.asyncio
async def test_asgi_raw_path_ignores_query_separator_defensively() -> None:
    status, body = await call_asgi_file_lookup(
        path="/wrong",
        raw_path=b"/files/%2e%2e?debug=true",
    )

    assert status == 200
    assert body == b'{"name":".."}'


@pytest.mark.asyncio
async def test_asgi_malformed_raw_path_falls_back_to_decoded_path() -> None:
    status, body = await call_asgi_file_lookup(
        path="/files/fallback",
        raw_path=b"/files/\xff",
    )

    assert status == 200
    assert body == b'{"name":"fallback"}'


@pytest.mark.asyncio
async def test_asgi_invalid_percent_encoded_utf8_falls_back_to_decoded_path() -> None:
    status, body = await call_asgi_file_lookup(
        path="/files/fallback",
        raw_path=b"/files/%ff",
    )

    assert status == 200
    assert body == b'{"name":"fallback"}'


@pytest.mark.asyncio
async def test_asgi_relative_raw_path_falls_back_to_decoded_path() -> None:
    status, body = await call_asgi_file_lookup(
        path="/files/fallback",
        raw_path=b"files/a%2Fb",
    )

    assert status == 200
    assert body == b'{"name":"fallback"}'


@pytest.mark.asyncio
async def test_asgi_path_falls_back_when_raw_path_is_not_available() -> None:
    status, body = await call_asgi_file_lookup(path="/files/report.pdf")

    assert status == 200
    assert body == b'{"name":"report.pdf"}'


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
async def test_asgi_duplicate_authorization_header_is_rejected_before_auth() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(_ctx: Request) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "GET",
            "path": "/private",
            "scheme": "http",
            "query_string": b"",
            "headers": [
                (b"host", b"localhost"),
                (b"authorization", b"Bearer deny"),
                (b"authorization", b"Bearer allow"),
            ],
            "client": ("127.0.0.1", 5000),
        },
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    assert sent[0]["status"] == 400
    assert response_body(sent) == b"Invalid Authorization header"
    assert auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_asgi_disconnect_aborts_incomplete_body_without_side_effects() -> None:
    app = Quater(debug=False)
    side_effects: list[bytes] = []

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        body = await request.body()
        side_effects.append(body)
        return body

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
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ],
    )

    assert sent[0]["status"] == 400
    assert (
        response_body(sent) == b"Client disconnected before request body was complete"
    )
    assert side_effects == []


@pytest.mark.asyncio
async def test_asgi_unsupported_http_receive_message_becomes_safe_500() -> None:
    app = Quater(debug=False)

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
        [{"type": "http.response.start"}],
    )

    assert sent[0]["status"] == 500
    assert response_body(sent) == b"Internal Server Error"


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
async def test_asgi_invalid_mutated_response_body_becomes_safe_500() -> None:
    app = Quater(debug=False)

    @app.get("/bad-response")
    async def bad_response() -> Response:
        response = Response(b"ok")
        response.body = cast(bytes, "not bytes")
        return response

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "GET",
            "path": "/bad-response",
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
    assert sent[0]["status"] == 500
    assert response_body(sent) == b"Internal Server Error"
    assert all(isinstance(message.get("body", b""), bytes) for message in body_messages)


@pytest.mark.asyncio
async def test_asgi_invalid_mutated_status_code_becomes_safe_500() -> None:
    app = Quater(debug=False)

    @app.get("/bad-status")
    async def bad_status() -> Response:
        response = Response(b"ok")
        response.status_code = 700
        return response

    sent = await call_asgi(
        app.asgi,
        {
            "type": "http",
            "method": "GET",
            "path": "/bad-status",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    assert sent[0]["status"] == 500
    assert response_body(sent) == b"Internal Server Error"


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
async def test_asgi_runs_response_finalizers_when_send_fails() -> None:
    events: list[str] = []
    app = Quater()

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "primary"
        finally:
            events.append("close")

    @app.get("/finalize", inject={"value": Resource(provider)})
    async def finalize(value: str) -> bytes:
        return value.encode()

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        if message["type"] == "http.response.body":
            raise RuntimeError("client disconnected")

    with pytest.raises(RuntimeError, match="client disconnected"):
        await app.asgi(
            {
                "type": "http",
                "method": "GET",
                "path": "/finalize",
                "scheme": "http",
                "query_string": b"",
                "headers": [(b"host", b"localhost")],
                "client": ("127.0.0.1", 5000),
            },
            receive,
            send,
        )

    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_asgi_runs_stream_finalizers_when_iterator_fails() -> None:
    events: list[str] = []
    sent: list[dict[str, object]] = []
    app = Quater()

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "primary"
        finally:
            events.append("close")

    async def chunks() -> AsyncIterator[bytes]:
        yield b"first"
        raise RuntimeError("stream failed")

    @app.get("/stream", inject={"value": Resource(provider)})
    async def stream(value: str) -> StreamResponse:
        assert value == "primary"
        return StreamResponse(chunks())

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        sent.append(dict(message))

    with pytest.raises(RuntimeError, match="stream failed"):
        await app.asgi(
            {
                "type": "http",
                "method": "GET",
                "path": "/stream",
                "scheme": "http",
                "query_string": b"",
                "headers": [(b"host", b"localhost")],
                "client": ("127.0.0.1", 5000),
            },
            receive,
            send,
        )

    assert events == ["open", "close"]
    assert response_body(sent) == b"first"


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
async def test_asgi_lifespan_reports_hook_failures_without_traceback() -> None:
    app = Quater()

    @app.on_startup
    async def startup() -> None:
        raise RuntimeError("database offline")

    sent = await call_asgi(
        app.asgi,
        {"type": "lifespan"},
        [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ],
    )

    assert sent == [
        {"type": "lifespan.startup.failed", "message": "database offline"},
        {"type": "lifespan.shutdown.complete"},
    ]


@pytest.mark.asyncio
async def test_asgi_lifespan_rejects_unknown_messages_loudly() -> None:
    with pytest.raises(ValueError, match="Unsupported ASGI lifespan message"):
        await call_asgi(
            Quater().asgi,
            {"type": "lifespan"},
            [{"type": "lifespan.ping"}],
        )


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


@pytest.mark.asyncio
async def test_asgi_rejects_unsupported_scope_types_loudly() -> None:
    with pytest.raises(ValueError, match="Unsupported ASGI scope type"):
        await call_asgi(Quater().asgi, {"type": "smtp"}, [])
