from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from inspect import isawaitable

import pytest

from quater import (
    BytesResponse,
    EmptyResponse,
    Quater,
    Request,
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


class FakeHTTPProtocol:
    def __init__(self, body: bytes = b"") -> None:
        self.body = body
        self.read_calls = 0
        self.kind: str | None = None
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.response_body: bytes = b""
        self.stream = FakeStreamTransport()

    async def __call__(self) -> bytes:
        self.read_calls += 1
        return self.body

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


class FakeWebSocketProtocol:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    def close(self, status: int | None) -> tuple[int, bool]:
        self.closed_with = status
        return (status or 1000, True)


async def call_rsgi(app: Quater, path: str, protocol: FakeHTTPProtocol) -> None:
    result = app.rsgi(FakeRSGIScope(path=path), protocol)
    assert isawaitable(result)
    await result


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
