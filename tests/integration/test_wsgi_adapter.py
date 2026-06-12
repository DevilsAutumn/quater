from __future__ import annotations

from collections.abc import AsyncIterator
from io import BytesIO
from typing import cast

import pytest

from quater import HTTPError, Quater, Request, Resource, Response, StreamResponse
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


def test_wsgi_preserves_handler_error_when_resource_rollback_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    app = Quater(debug=True)
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

    status, _headers, body = call_wsgi(app, base_environ(path="/bad"))

    assert status == "400 Bad Request"
    assert body == b"bad input"
    assert events == ["open", "rollback", "close"]
    assert "Resource cleanup failed" in caplog.text
    assert "rollback failed" in caplog.text


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


def test_wsgi_unknown_status_codes_use_safe_status_phrase() -> None:
    app = Quater()

    @app.get("/custom")
    async def custom() -> Response:
        return Response(b"custom", status_code=599)

    status, _, body = call_wsgi(app, base_environ(path="/custom"))

    assert status == "599 Unknown"
    assert body == b"custom"


def test_wsgi_invalid_mutated_response_body_becomes_safe_500() -> None:
    app = Quater(debug=False)

    @app.get("/bad-response")
    async def bad_response() -> Response:
        response = Response(b"ok")
        response.body = cast(bytes, "not bytes")
        return response

    status, _, body = call_wsgi(app, base_environ(path="/bad-response"))

    assert status == "500 Internal Server Error"
    assert body == b"Internal Server Error"


def test_wsgi_invalid_mutated_status_code_becomes_safe_500() -> None:
    app = Quater(debug=False)

    @app.get("/bad-status")
    async def bad_status() -> Response:
        response = Response(b"ok")
        response.status_code = 700
        return response

    status, _, body = call_wsgi(app, base_environ(path="/bad-status"))

    assert status == "500 Internal Server Error"
    assert body == b"Internal Server Error"


def test_wsgi_request_parts_include_query_scheme_client_and_host_fallback() -> None:
    app = Quater()
    environ = base_environ(path="/inspect")
    environ["QUERY_STRING"] = "page=2"
    environ["wsgi.url_scheme"] = "https"
    environ["REMOTE_ADDR"] = "10.0.0.5"

    @app.get("/inspect")
    async def inspect_request(request: Request) -> dict[str, object]:
        return {
            "scheme": request.scheme,
            "page": request.query["page"],
            "client": request.client,
            "host": request.headers["host"],
        }

    status, _, body = call_wsgi(app, environ)

    assert status == "200 OK"
    assert body == (
        b'{"scheme":"https","page":"2","client":"10.0.0.5","host":"localhost:80"}'
    )


def test_wsgi_path_info_recovers_utf8_path_bytes() -> None:
    app = Quater()

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    status, _, body = call_wsgi(app, base_environ(path="/items/caf\u00c3\u00a9"))

    assert status == "200 OK"
    assert body == b'{"item_id":"caf\xc3\xa9"}'


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


def test_wsgi_negative_content_length_reads_no_body() -> None:
    app = Quater()
    stream = CountingInput(b"should-not-be-read")
    environ = base_environ(method="POST", path="/echo", body=b"should-not-be-read")
    environ["CONTENT_LENGTH"] = "-50"
    environ["wsgi.input"] = stream

    @app.post("/echo")
    async def echo(request: Request) -> bytes:
        return await request.body()

    status, _, body = call_wsgi(app, environ)

    assert status == "400 Bad Request"
    assert body == b"Invalid Content-Length header"
    assert stream.read_calls == 0


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


def test_wsgi_runs_response_finalizers_when_streaming_body_fails() -> None:
    events: list[str] = []
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

    with pytest.raises(RuntimeError, match="stream failed"):
        call_wsgi(app, base_environ(path="/stream"))

    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_wsgi_can_be_called_from_an_existing_event_loop() -> None:
    app = Quater()

    @app.get("/hello")
    async def hello() -> str:
        return "ok"

    status, _, body = call_wsgi(app, base_environ(path="/hello"))

    assert status == "200 OK"
    assert body == b"ok"


def test_wsgi_warns_on_first_request_when_startup_hook_is_registered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater()

    @app.on_startup
    async def startup() -> None:  # pragma: no cover - never runs under WSGI
        pass

    @app.get("/hello")
    async def hello() -> str:
        return "ok"

    with caplog.at_level("WARNING", logger="quater"):
        call_wsgi(app, base_environ(path="/hello"))
        # The warning fires once, not on every request.
        call_wsgi(app, base_environ(path="/hello"))

    assert caplog.text.count("compatibility-only") == 1
    assert "on_startup/on_shutdown" in caplog.text


def test_wsgi_warns_for_shutdown_only_lifespan_hook(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater()

    @app.on_shutdown
    async def shutdown() -> None:  # pragma: no cover - never runs under WSGI
        pass

    @app.get("/hello")
    async def hello() -> str:
        return "ok"

    with caplog.at_level("WARNING", logger="quater"):
        call_wsgi(app, base_environ(path="/hello"))

    assert "compatibility-only" in caplog.text


def test_wsgi_warns_even_when_adapter_is_captured_before_hooks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Mirrors `application = app.wsgi` declared above the @app.on_startup
    # decorators: the adapter is cached before any hook exists, so a
    # construction-time check would miss the warning.
    app = Quater()

    @app.get("/hello")
    async def hello() -> str:
        return "ok"

    wsgi_app = app.wsgi  # captured first

    @app.on_startup
    async def startup() -> None:  # pragma: no cover - never runs under WSGI
        pass

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> object:
        return None

    with caplog.at_level("WARNING", logger="quater"):
        b"".join(wsgi_app(base_environ(path="/hello"), start_response))

    assert "compatibility-only" in caplog.text


def test_wsgi_does_not_warn_without_lifespan_hooks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater()

    @app.get("/hello")
    async def hello() -> str:
        return "ok"

    with caplog.at_level("WARNING", logger="quater"):
        call_wsgi(app, base_environ(path="/hello"))

    assert "compatibility-only" not in caplog.text
