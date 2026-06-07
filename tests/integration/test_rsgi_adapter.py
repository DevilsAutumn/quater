from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable
from dataclasses import dataclass
from inspect import isawaitable
from typing import cast

import pytest

from quater import (
    BytesResponse,
    EmptyResponse,
    HTTPError,
    Quater,
    Request,
    Resource,
    Response,
    StreamResponse,
    TextResponse,
)


class FakeRSGIHeaders:
    def __init__(self, headers: list[tuple[str, str]] | None = None) -> None:
        self._headers = headers or []

    def items(self) -> list[tuple[str, str]]:
        return list(self._headers)


@dataclass(slots=True)
class FakeRSGIScope:
    method: str = "GET"
    path: str = "/"
    query_string: str = ""
    scheme: str = "http"
    client: str = "127.0.0.1:5000"
    authority: str | None = "localhost"
    proto: str = "http"
    headers: FakeRSGIHeaders = FakeRSGIHeaders()


class FakeStreamTransport:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.chunks.append(data)


class FailingStreamTransport(FakeStreamTransport):
    async def send_bytes(self, data: bytes) -> None:
        await super().send_bytes(data)
        raise RuntimeError("client disconnected")


class FakeHTTPProtocol:
    def __init__(self, body: bytes = b"", chunks: list[bytes] | None = None) -> None:
        self._request_body = body
        self._chunks = chunks
        self.read_calls = 0
        self.kind: str | None = None
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.response_body: bytes = b""
        self.stream = FakeStreamTransport()

    async def __call__(self) -> bytes:
        self.read_calls += 1
        return self._request_body

    async def __aiter__(self) -> AsyncGenerator[bytes, None]:
        chunks = self._chunks if self._chunks is not None else [self._request_body]
        for chunk in chunks:
            self.read_calls += 1
            yield chunk

    def response_empty(self, status: int, headers: list[tuple[str, str]]) -> None:
        self.kind = "empty"
        self.status = status
        self.headers = headers

    def response_bytes(
        self,
        status: int,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> None:
        self.kind = "bytes"
        self.status = status
        self.headers = headers
        self.response_body = body

    def response_stream(
        self,
        status: int,
        headers: list[tuple[str, str]],
    ) -> FakeStreamTransport:
        self.kind = "stream"
        self.status = status
        self.headers = headers
        return self.stream


class FailingStreamHTTPProtocol(FakeHTTPProtocol):
    def __init__(self, body: bytes = b"") -> None:
        super().__init__(body=body)
        self.stream = FailingStreamTransport()


class FakeWebSocketProtocol:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    def close(self, status: int | None) -> tuple[int, bool]:
        self.closed_with = status
        return (status or 1000, True)


class FakeRSGIScheduler:
    def __init__(self) -> None:
        self.callbacks: list[Awaitable[None]] = []

    def _run(self, callback: Awaitable[None]) -> None:
        self.callbacks.append(callback)


class FakeRSGILoop:
    def __init__(self) -> None:
        self.callbacks: list[Awaitable[None]] = []

    def run_until_complete(self, callback: Awaitable[None]) -> None:
        self.callbacks.append(callback)


async def call_rsgi(app: Quater, path: str, protocol: FakeHTTPProtocol) -> None:
    result = app.rsgi(FakeRSGIScope(path=path), protocol)
    assert isawaitable(result)
    await result


@pytest.mark.asyncio
async def test_rsgi_preserves_handler_error_when_resource_rollback_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater(debug=True)
    events: list[str] = []
    caplog.set_level("ERROR", logger="quater.finalize")

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "primary"
        except HTTPError:
            events.append("rollback")
            raise RuntimeError("rollback failed") from None
        finally:
            events.append("close")

    @app.get("/bad", inject={"value": Resource(provider)})
    async def bad(value: str) -> dict[str, str]:
        raise HTTPError("bad input", status_code=400)

    protocol = FakeHTTPProtocol()

    await call_rsgi(app, "/bad", protocol)

    assert protocol.status == 400
    assert protocol.response_body == b"bad input"
    assert events == ["open", "rollback", "close"]
    assert "Resource cleanup failed" in caplog.text
    assert "rollback failed" in caplog.text


@pytest.mark.asyncio
async def test_rsgi_maps_common_response_shapes() -> None:
    app = Quater()

    @app.get("/json")
    async def json() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/bytes")
    async def bytes_response() -> BytesResponse:
        return BytesResponse(b"raw")

    @app.get("/text")
    async def text() -> TextResponse:
        return TextResponse("hello")

    @app.get("/empty")
    async def empty() -> EmptyResponse:
        return EmptyResponse()

    json_proto = FakeHTTPProtocol()
    bytes_proto = FakeHTTPProtocol()
    text_proto = FakeHTTPProtocol()
    empty_proto = FakeHTTPProtocol()

    await call_rsgi(app, "/json", json_proto)
    await call_rsgi(app, "/bytes", bytes_proto)
    await call_rsgi(app, "/text", text_proto)
    await call_rsgi(app, "/empty", empty_proto)

    assert json_proto.kind == "bytes"
    assert json_proto.response_body == b'{"ok":true}'
    assert dict(json_proto.headers)["content-type"] == "application/json"
    assert bytes_proto.response_body == b"raw"
    assert text_proto.response_body == b"hello"
    assert empty_proto.kind == "empty"
    assert empty_proto.status == 204


@pytest.mark.asyncio
async def test_rsgi_invalid_mutated_response_body_becomes_safe_500() -> None:
    app = Quater(debug=False)

    @app.get("/bad-response")
    async def bad_response() -> Response:
        response = Response(b"ok")
        response.body = cast(bytes, "not bytes")
        return response

    protocol = FakeHTTPProtocol()

    await call_rsgi(app, "/bad-response", protocol)

    assert protocol.kind == "bytes"
    assert protocol.status == 500
    assert protocol.response_body == b"Internal Server Error"


@pytest.mark.asyncio
async def test_rsgi_invalid_mutated_status_code_becomes_safe_500() -> None:
    app = Quater(debug=False)

    @app.get("/bad-status")
    async def bad_status() -> Response:
        response = Response(b"ok")
        response.status_code = 700
        return response

    protocol = FakeHTTPProtocol()

    await call_rsgi(app, "/bad-status", protocol)

    assert protocol.kind == "bytes"
    assert protocol.status == 500
    assert protocol.response_body == b"Internal Server Error"


@pytest.mark.asyncio
async def test_rsgi_stream_response_uses_stream_transport() -> None:
    app = Quater()

    async def chunks() -> AsyncIterator[bytes]:
        yield b"a"
        yield b"b"

    @app.get("/stream")
    async def stream() -> StreamResponse:
        return StreamResponse(chunks())

    protocol = FakeHTTPProtocol()

    await call_rsgi(app, "/stream", protocol)

    assert protocol.kind == "stream"
    assert protocol.stream.chunks == [b"a", b"b"]


@pytest.mark.asyncio
async def test_rsgi_finalizes_resources_after_stream_response() -> None:
    app = Quater()
    events: list[str] = []

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "primary"
        finally:
            events.append("close")

    async def chunks() -> AsyncIterator[bytes]:
        yield b"first"
        yield b"second"

    @app.get("/stream", inject={"value": Resource(provider)})
    async def stream(value: str) -> StreamResponse:
        assert value == "primary"
        return StreamResponse(chunks())

    protocol = FakeHTTPProtocol()

    await call_rsgi(app, "/stream", protocol)

    assert protocol.kind == "stream"
    assert protocol.stream.chunks == [b"first", b"second"]
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_rsgi_finalizes_resources_after_regular_response() -> None:
    app = Quater()
    events: list[str] = []

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "primary"
        finally:
            events.append("close")

    @app.get("/finalize", inject={"value": Resource(provider)})
    async def finalize(value: str) -> bytes:
        return value.encode()

    protocol = FakeHTTPProtocol()

    await call_rsgi(app, "/finalize", protocol)

    assert protocol.response_body == b"primary"
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_rsgi_runs_finalizers_when_stream_send_fails() -> None:
    app = Quater()
    events: list[str] = []

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "primary"
        finally:
            events.append("close")

    async def chunks() -> AsyncIterator[bytes]:
        yield b"first"
        yield b"second"

    @app.get("/stream", inject={"value": Resource(provider)})
    async def stream(value: str) -> StreamResponse:
        assert value == "primary"
        return StreamResponse(chunks())

    protocol = FailingStreamHTTPProtocol()
    result = app.rsgi(FakeRSGIScope(path="/stream"), protocol)

    assert isawaitable(result)
    with pytest.raises(RuntimeError, match="client disconnected"):
        await result

    assert protocol.stream.chunks == [b"first"]
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_rsgi_request_body_is_lazy_and_cached_by_request() -> None:
    app = Quater()

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        first = await request.body()
        second = await request.body()
        assert second is first
        return first

    protocol = FakeHTTPProtocol(body=b"hello")
    result = app.rsgi(FakeRSGIScope(method="POST", path="/echo"), protocol)

    assert isawaitable(result)
    await result
    assert protocol.read_calls == 1
    assert protocol.response_body == b"hello"


@pytest.mark.asyncio
async def test_rsgi_multiple_body_chunks_reach_handler_without_loss() -> None:
    app = Quater()

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    protocol = FakeHTTPProtocol(chunks=[b"hello ", b"world"])
    result = app.rsgi(FakeRSGIScope(method="POST", path="/echo"), protocol)

    assert isawaitable(result)
    await result
    assert protocol.status == 200
    assert protocol.response_body == b"hello world"
    assert protocol.read_calls == 2


@pytest.mark.asyncio
async def test_rsgi_body_limit_allows_exact_limit_across_chunks() -> None:
    app = Quater(max_body_size=5)

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    protocol = FakeHTTPProtocol(chunks=[b"", b"12", b"", b"345"])
    result = app.rsgi(FakeRSGIScope(method="POST", path="/echo"), protocol)

    assert isawaitable(result)
    await result
    assert protocol.status == 200
    assert protocol.response_body == b"12345"
    assert protocol.read_calls == 4


@pytest.mark.asyncio
async def test_rsgi_body_limit_returns_safe_error() -> None:
    app = Quater(max_body_size=2)

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    protocol = FakeHTTPProtocol(body=b"abc")
    result = app.rsgi(FakeRSGIScope(method="POST", path="/echo"), protocol)

    assert isawaitable(result)
    await result
    assert protocol.status == 413
    assert protocol.response_body == b"Payload Too Large"


@pytest.mark.asyncio
async def test_rsgi_body_limit_stops_reading_oversized_chunked_body() -> None:
    app = Quater(max_body_size=4)

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    protocol = FakeHTTPProtocol(chunks=[b"12", b"345", b"ignored"])
    result = app.rsgi(FakeRSGIScope(method="POST", path="/echo"), protocol)

    assert isawaitable(result)
    await result
    assert protocol.status == 413
    assert protocol.response_body == b"Payload Too Large"
    assert protocol.read_calls == 2


@pytest.mark.asyncio
async def test_rsgi_rejects_host_and_authority_mismatch() -> None:
    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    protocol = FakeHTTPProtocol()
    result = app.rsgi(
        FakeRSGIScope(
            path="/health",
            authority="evil.example.com",
            headers=FakeRSGIHeaders([("host", "api.example.com")]),
        ),
        protocol,
    )

    assert isawaitable(result)
    await result
    assert protocol.status == 400
    assert protocol.response_body == b"Invalid Host header"


def test_rsgi_websocket_scope_closes_without_router_dispatch() -> None:
    app = Quater()
    calls = 0

    @app.get("/ws")
    async def route() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    protocol = FakeWebSocketProtocol()
    result = app.rsgi(FakeRSGIScope(proto="websocket", path="/ws"), protocol)

    assert result == (1003, True)
    assert protocol.closed_with == 1003
    assert calls == 0


@pytest.mark.asyncio
async def test_rsgi_lifespan_callbacks_run_app_startup_and_shutdown() -> None:
    app = Quater()
    scheduler = FakeRSGIScheduler()
    events: list[str] = []

    @app.on_startup
    async def startup() -> None:
        events.append("startup")

    @app.on_shutdown
    async def shutdown() -> None:
        events.append("shutdown")

    app.__rsgi_init__(scheduler)
    app.__rsgi_init__(scheduler)
    app.__rsgi_del__(scheduler)
    app.__rsgi_del__(scheduler)

    for callback in scheduler.callbacks:
        await callback

    assert events == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_rsgi_lifespan_callbacks_support_granian_event_loop() -> None:
    app = Quater()
    loop = FakeRSGILoop()
    events: list[str] = []

    @app.on_startup
    async def startup() -> None:
        events.append("startup")

    @app.on_shutdown
    async def shutdown() -> None:
        events.append("shutdown")

    app.__rsgi_init__(loop)
    app.__rsgi_del__(loop)

    for callback in loop.callbacks:
        await callback

    assert events == ["startup", "shutdown"]


def test_rsgi_lifespan_callbacks_fail_loudly_without_runner() -> None:
    app = Quater()

    with pytest.raises(RuntimeError, match="RSGI lifespan runner is unavailable"):
        app.__rsgi_init__(object())
