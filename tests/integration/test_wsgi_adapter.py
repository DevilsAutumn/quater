from __future__ import annotations

from io import BytesIO
from typing import cast

import pytest

from quater import Quater, Request
from quater.adapters.wsgi import WSGIEnvironment


class CountingInput(BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.read_calls = 0

    def read(self, size: int | None = -1) -> bytes:
        self.read_calls += 1
        return super().read(size)


def call_wsgi(
    app: Quater,
    environ: WSGIEnvironment,
) -> tuple[str, list[tuple[str, str]], bytes]:
    captured: dict[str, object] = {}

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> object:
        captured["status"] = status
        captured["headers"] = headers
        captured["exc_info"] = exc_info
        return None

    body = b"".join(app.wsgi(environ, start_response))
    return (
        str(captured["status"]),
        list(cast(list[tuple[str, str]], captured["headers"])),
        body,
    )


def base_environ(
    *,
    method: str = "GET",
    path: str = "/",
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> WSGIEnvironment:
    environ: WSGIEnvironment = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": CountingInput(body),
        "wsgi.url_scheme": "http",
    }
    if body:
        environ["CONTENT_LENGTH"] = str(len(body))
    for name, value in (headers or {}).items():
        environ[f"HTTP_{name.upper().replace('-', '_')}"] = value
    return environ


def test_wsgi_route_response_maps_status_headers_and_body() -> None:
    app = Quater()

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"hello": "world"}

    status, headers, body = call_wsgi(app, base_environ(path="/hello"))

    header_map = dict(headers)
    assert status == "200 OK"
    assert body == b'{"hello":"world"}'
    assert header_map["content-type"] == "application/json"
    assert header_map["x-content-type-options"] == "nosniff"


def test_wsgi_input_stream_is_read_once_by_handler() -> None:
    app = Quater()
    stream = CountingInput(b"abc")
    environ = base_environ(method="POST", path="/echo", body=b"abc")
    environ["wsgi.input"] = stream

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        first = await request.body()
        second = await request.body()
        assert second is first
        return first

    status, _, body = call_wsgi(app, environ)

    assert status == "200 OK"
    assert body == b"abc"
    assert stream.read_calls == 1


def test_wsgi_body_limit_uses_content_length_before_stream_read() -> None:
    app = Quater(max_body_size=2)
    stream = CountingInput(b"abc")
    environ = base_environ(method="POST", path="/echo", body=b"abc")
    environ["wsgi.input"] = stream

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    status, _, body = call_wsgi(app, environ)

    assert status.startswith("413 ")
    assert body == b"Payload Too Large"
    assert stream.read_calls == 0


def test_wsgi_body_limit_caps_reads_without_content_length() -> None:
    app = Quater(max_body_size=2)
    stream = CountingInput(b"abcdef")
    environ = base_environ(method="POST", path="/echo", body=b"abcdef")
    del environ["CONTENT_LENGTH"]
    environ["wsgi.input"] = stream

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    status, _, body = call_wsgi(app, environ)

    assert status.startswith("413 ")
    assert body == b"Payload Too Large"
    assert stream.read_calls == 1
    assert stream.tell() == 3


@pytest.mark.asyncio
async def test_wsgi_can_be_called_from_an_existing_event_loop() -> None:
    app = Quater()

    @app.get("/hello")
    async def hello() -> str:
        return "ok"

    status, _, body = call_wsgi(app, base_environ(path="/hello"))

    assert status == "200 OK"
    assert body == b"ok"
