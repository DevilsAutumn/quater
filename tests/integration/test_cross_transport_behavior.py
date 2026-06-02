from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from inspect import isawaitable
from io import BytesIO
from typing import Any, cast

import pytest

from quater import AuthConfig, Quater, Request
from quater.adapters.asgi import ASGIMessage
from quater.adapters.wsgi import WSGIEnvironment
from quater.typing import AuthContext


class RSGIHeaders:
    def __init__(self, headers: list[tuple[str, str]]) -> None:
        self._headers = headers

    def items(self) -> list[tuple[str, str]]:
        return list(self._headers)


class RSGIScope:
    proto: str = "http"
    query_string: str = ""
    scheme: str = "http"
    client: str = "127.0.0.1:5000"
    authority: str | None = None

    def __init__(
        self,
        *,
        method: str,
        path: str,
        headers: list[tuple[str, str]],
    ) -> None:
        self.method = method
        self.path = path
        self.headers = RSGIHeaders(headers)


class RSGIProtocol:
    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.body = b""

    async def __call__(self) -> bytes:
        return b""

    def response_empty(self, status: int, headers: list[tuple[str, str]]) -> None:
        self.status = status
        self.headers = headers

    def response_bytes(
        self,
        status: int,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> None:
        self.status = status
        self.headers = headers
        self.body = body

    def response_stream(
        self,
        status: int,
        headers: list[tuple[str, str]],
    ) -> RSGIStreamTransport:
        raise AssertionError("unexpected streaming response")


class RSGIStreamTransport:
    async def send_bytes(self, data: bytes) -> None:
        raise AssertionError("unexpected streaming response")


@dataclass(frozen=True, slots=True)
class PathParamCase:
    name: str
    asgi_path: str
    asgi_raw_path: bytes
    rsgi_path: str
    wsgi_path: str
    expected_status: int
    expected_body: bytes


async def asgi_response(
    app: Quater,
    *,
    host: str,
    authorization: str,
) -> tuple[int, dict[str, str], bytes]:
    sent: list[dict[str, object]] = []

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        sent.append(dict(message))

    await app.asgi(
        {
            "type": "http",
            "method": "GET",
            "path": "/me",
            "scheme": "http",
            "query_string": b"",
            "headers": [
                (b"host", host.encode("latin-1")),
                (b"authorization", authorization.encode("latin-1")),
            ],
            "client": ("127.0.0.1", 5000),
        },
        receive,
        send,
    )
    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    headers = {
        name.decode("latin-1"): value.decode("latin-1")
        for name, value in cast(list[tuple[bytes, bytes]], start["headers"])
    }
    body = b"".join(
        cast(bytes, message.get("body", b""))
        for message in sent
        if message["type"] == "http.response.body"
    )
    return cast(int, start["status"]), headers, body


async def asgi_path_response(
    app: Quater,
    *,
    path: str,
    raw_path: bytes,
) -> tuple[int, bytes]:
    sent: list[dict[str, object]] = []

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        sent.append(dict(message))

    await app.asgi(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": raw_path,
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 5000),
        },
        receive,
        send,
    )
    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    body = b"".join(
        cast(bytes, message.get("body", b""))
        for message in sent
        if message["type"] == "http.response.body"
    )
    return cast(int, start["status"]), body


def wsgi_response(
    app: Quater,
    *,
    host: str,
    authorization: str,
) -> tuple[int, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> object:
        captured["status"] = status
        captured["headers"] = headers
        return None

    environ: WSGIEnvironment = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/me",
        "QUERY_STRING": "",
        "SERVER_NAME": "internal",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": host,
        "HTTP_AUTHORIZATION": authorization,
        "wsgi.input": BytesIO(b""),
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
    }
    body = b"".join(app.wsgi(environ, start_response))
    status_code = int(str(captured["status"]).split(" ", 1)[0])
    headers = cast(list[tuple[str, str]], captured["headers"])
    return status_code, dict(headers), body


def wsgi_path_response(app: Quater, *, path: str) -> tuple[int, bytes]:
    captured: dict[str, object] = {}

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> object:
        captured["status"] = status
        captured["headers"] = headers
        return None

    body = b"".join(
        app.wsgi(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": path,
                "QUERY_STRING": "",
                "SERVER_NAME": "localhost",
                "SERVER_PORT": "80",
                "SERVER_PROTOCOL": "HTTP/1.1",
                "wsgi.input": BytesIO(b""),
                "wsgi.url_scheme": "http",
                "REMOTE_ADDR": "127.0.0.1",
            },
            start_response,
        )
    )
    status_code = int(str(captured["status"]).split(" ", 1)[0])
    return status_code, body


async def rsgi_response(
    app: Quater,
    *,
    host: str,
    authorization: str,
) -> tuple[int, dict[str, str], bytes]:
    protocol = RSGIProtocol()
    result = app.rsgi(
        RSGIScope(
            method="GET",
            path="/me",
            headers=[("host", host), ("authorization", authorization)],
        ),
        protocol,
    )
    assert isawaitable(result)
    await result
    assert protocol.status is not None
    return protocol.status, dict(protocol.headers), protocol.body


async def rsgi_path_response(app: Quater, *, path: str) -> tuple[int, bytes]:
    protocol = RSGIProtocol()
    result = app.rsgi(
        RSGIScope(
            method="GET",
            path=path,
            headers=[("host", "localhost")],
        ),
        protocol,
    )
    assert isawaitable(result)
    await result
    assert protocol.status is not None
    return protocol.status, protocol.body


def test_adapter_properties_are_cached_per_app_instance() -> None:
    app = Quater()

    assert app.asgi is app.asgi
    assert app.rsgi is app.rsgi
    assert app.__rsgi__ is app.rsgi
    assert app.wsgi is app.wsgi


def make_path_param_app() -> Quater:
    app = Quater()

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/files/{name}")
    async def file(name: str) -> dict[str, str]:
        return {"name": name}

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    (
        PathParamCase(
            name="non_ascii",
            asgi_path="/items/caf\u00e9",
            asgi_raw_path=b"/items/caf%C3%A9",
            rsgi_path="/items/caf\u00e9",
            wsgi_path="/items/caf\u00c3\u00a9",
            expected_status=200,
            expected_body=b'{"item_id":"caf\xc3\xa9"}',
        ),
        PathParamCase(
            name="encoded_space_is_data",
            asgi_path="/items/red blue",
            asgi_raw_path=b"/items/red%20blue",
            rsgi_path="/items/red blue",
            wsgi_path="/items/red blue",
            expected_status=200,
            expected_body=b'{"item_id":"red blue"}',
        ),
        PathParamCase(
            name="encoded_percent_is_data",
            asgi_path="/items/100%",
            asgi_raw_path=b"/items/100%25",
            rsgi_path="/items/100%",
            wsgi_path="/items/100%",
            expected_status=200,
            expected_body=b'{"item_id":"100%"}',
        ),
        PathParamCase(
            name="double_encoded_slash_decodes_once",
            asgi_path="/items/a%2Fb",
            asgi_raw_path=b"/items/a%252Fb",
            rsgi_path="/items/a%2Fb",
            wsgi_path="/items/a%2Fb",
            expected_status=200,
            expected_body=b'{"item_id":"a%2Fb"}',
        ),
        PathParamCase(
            name="encoded_question_mark_is_data",
            asgi_path="/items/name?debug",
            asgi_raw_path=b"/items/name%3Fdebug?ignored=true",
            rsgi_path="/items/name?debug",
            wsgi_path="/items/name?debug",
            expected_status=200,
            expected_body=b'{"item_id":"name?debug"}',
        ),
        PathParamCase(
            name="encoded_slash_is_segment_split",
            asgi_path="/items/a/b",
            asgi_raw_path=b"/items/a%2Fb",
            rsgi_path="/items/a/b",
            wsgi_path="/items/a/b",
            expected_status=404,
            expected_body=b"Not found: /items/a/b",
        ),
        PathParamCase(
            name="encoded_dotdot_is_segment_value",
            asgi_path="/files/..",
            asgi_raw_path=b"/files/%2e%2e",
            rsgi_path="/files/..",
            wsgi_path="/files/..",
            expected_status=200,
            expected_body=b'{"name":".."}',
        ),
        PathParamCase(
            name="encoded_traversal_stays_extra_segments",
            asgi_path="/files/../../secret",
            asgi_raw_path=b"/files/..%2F..%2Fsecret",
            rsgi_path="/files/../../secret",
            wsgi_path="/files/../../secret",
            expected_status=404,
            expected_body=b"Not found: /files/../../secret",
        ),
    ),
    ids=lambda case: case.name,
)
async def test_encoded_path_params_match_across_http_adapters(
    case: PathParamCase,
) -> None:
    app = make_path_param_app()
    expected = (case.expected_status, case.expected_body)

    assert (
        await asgi_path_response(
            app,
            path=case.asgi_path,
            raw_path=case.asgi_raw_path,
        )
        == expected
    )
    assert wsgi_path_response(app, path=case.wsgi_path) == expected
    assert await rsgi_path_response(app, path=case.rsgi_path) == expected


@pytest.mark.asyncio
async def test_app_object_is_callable_for_all_http_transports() -> None:
    app = make_app([], [])

    asgi_sent: list[dict[str, object]] = []

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Mapping[str, Any]) -> None:
        asgi_sent.append(dict(message))

    await app(
        {
            "type": "http",
            "method": "GET",
            "path": "/me",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"api.example.com"), (b"authorization", b"asgi")],
            "client": ("127.0.0.1", 5000),
        },
        receive,
        send,
    )
    asgi_start = next(
        message for message in asgi_sent if message["type"] == "http.response.start"
    )

    wsgi_captured: dict[str, object] = {}

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> object:
        wsgi_captured["status"] = status
        wsgi_captured["headers"] = headers
        return None

    wsgi_body = b"".join(
        app(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/me",
                "QUERY_STRING": "",
                "SERVER_NAME": "api.example.com",
                "SERVER_PORT": "80",
                "SERVER_PROTOCOL": "HTTP/1.1",
                "HTTP_HOST": "api.example.com",
                "HTTP_AUTHORIZATION": "wsgi",
                "wsgi.input": BytesIO(b""),
                "wsgi.url_scheme": "http",
                "REMOTE_ADDR": "127.0.0.1",
            },
            start_response,
        )
    )

    protocol = RSGIProtocol()
    rsgi_result = app(
        RSGIScope(
            method="GET",
            path="/me",
            headers=[("host", "api.example.com"), ("authorization", "rsgi")],
        ),
        protocol,
    )
    assert isawaitable(rsgi_result)
    await rsgi_result

    assert asgi_start["status"] == 200
    assert str(wsgi_captured["status"]).startswith("200 ")
    assert wsgi_body == b'{"subject":"wsgi"}'
    assert protocol.status == 200
    assert protocol.body == b'{"subject":"rsgi"}'


def make_app(auth_subjects: list[str], handler_calls: list[str]) -> Quater:
    async def authenticate(ctx: Request) -> AuthContext | None:
        subject = ctx.headers.get("authorization")
        if subject is None:
            return None
        auth_subjects.append(subject)
        return AuthContext(subject=subject)

    app = Quater(
        allowed_hosts=["api.example.com"],
        auth=[AuthConfig(authenticate, surfaces=["api"])],
    )
    app.state.transport_marker = "shared"

    @app.get("/me")
    async def me(request: Request) -> dict[str, str]:
        assert request.app is app
        assert request.app.state.transport_marker == "shared"
        assert request.auth is not None
        handler_calls.append(request.auth.subject)
        return {"subject": request.auth.subject}

    return app


@pytest.mark.asyncio
async def test_http_adapters_share_security_auth_and_dispatch_behavior() -> None:
    auth_subjects: list[str] = []
    handler_calls: list[str] = []
    app = make_app(auth_subjects, handler_calls)

    responses = [
        await asgi_response(app, host="api.example.com", authorization="user_1"),
        wsgi_response(app, host="api.example.com", authorization="user_1"),
        await rsgi_response(app, host="api.example.com", authorization="user_1"),
    ]

    for status, headers, body in responses:
        assert status == 200
        assert body == b'{"subject":"user_1"}'
        assert headers["x-content-type-options"] == "nosniff"
    assert auth_subjects == ["user_1", "user_1", "user_1"]
    assert handler_calls == ["user_1", "user_1", "user_1"]


@pytest.mark.asyncio
async def test_allowed_host_rejection_is_transport_independent() -> None:
    auth_subjects: list[str] = []
    handler_calls: list[str] = []
    app = make_app(auth_subjects, handler_calls)

    responses = [
        await asgi_response(app, host="evil.example.com", authorization="user_1"),
        wsgi_response(app, host="evil.example.com", authorization="user_1"),
        await rsgi_response(app, host="evil.example.com", authorization="user_1"),
    ]

    for status, headers, body in responses:
        assert status == 400
        assert body == b"Invalid Host header"
        assert headers["x-content-type-options"] == "nosniff"
    assert auth_subjects == []
    assert handler_calls == []
