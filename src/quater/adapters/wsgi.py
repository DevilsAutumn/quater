"""WSGI adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol, TypeAlias, TypeVar, cast

from quater._finalize import run_response_finalizers
from quater.adapters._shared import (
    QuaterApplication,
    collect_response_body,
    request_from_parts,
    response_headers,
    response_status,
)
from quater.datastructures import HeaderItems
from quater.exceptions import PayloadTooLargeError
from quater.request import BodyReader

WSGIEnvironment: TypeAlias = dict[str, object]

T = TypeVar("T")


class WSGIInput(Protocol):
    def read(self, size: int = -1) -> bytes: ...


class StartResponse(Protocol):
    def __call__(
        self,
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object | None = None,
    ) -> object: ...


class WSGIAdapter:
    """Synchronous WSGI callable for compatibility deployments."""

    __slots__ = ("_app",)

    def __init__(self, app: QuaterApplication) -> None:
        self._app = app

    def __call__(
        self,
        environ: WSGIEnvironment,
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        status_code, headers, body = _run_async(self._handle(environ))
        start_response(response_status(status_code), headers, None)
        return body

    async def _handle(
        self,
        environ: WSGIEnvironment,
    ) -> tuple[int, list[tuple[str, str]], list[bytes]]:
        request = request_from_parts(
            method=str(environ.get("REQUEST_METHOD", "GET")),
            path=_path_from_environ(environ),
            scheme=str(environ.get("wsgi.url_scheme", "http")),
            headers=_headers_from_environ(environ),
            query_string=str(environ.get("QUERY_STRING", "")),
            body=_body_reader(environ, self._app.config.max_body_size),
            client=_optional_string(environ.get("REMOTE_ADDR")),
        )
        response = await self._app.handle(request)
        try:
            return (
                response.status_code,
                response_headers(response),
                await collect_response_body(response),
            )
        finally:
            await run_response_finalizers(response)


def _headers_from_environ(environ: WSGIEnvironment) -> HeaderItems:
    headers: list[tuple[str, str]] = []
    if "CONTENT_TYPE" in environ:
        headers.append(("content-type", str(environ["CONTENT_TYPE"])))
    if "CONTENT_LENGTH" in environ:
        headers.append(("content-length", str(environ["CONTENT_LENGTH"])))

    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        header_name = key[5:].replace("_", "-").lower()
        headers.append((header_name, str(value)))

    if not any(name == "host" for name, _ in headers):
        host = _server_host(environ)
        if host is not None:
            headers.append(("host", host))

    return tuple(headers)


def _path_from_environ(environ: WSGIEnvironment) -> str:
    path = str(environ.get("PATH_INFO", "/") or "/")
    try:
        return path.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return path


def _body_reader(environ: WSGIEnvironment, max_body_size: int) -> BodyReader:
    stream = cast(WSGIInput | None, environ.get("wsgi.input"))

    async def read() -> bytes:
        if stream is None:
            return b""
        content_length = _content_length(environ)
        if content_length is None:
            body = stream.read(max_body_size + 1)
            if len(body) > max_body_size:
                raise PayloadTooLargeError
            return body
        if content_length > max_body_size:
            raise PayloadTooLargeError
        return stream.read(content_length)

    return read


def _content_length(environ: WSGIEnvironment) -> int | None:
    value = environ.get("CONTENT_LENGTH")
    if value in (None, ""):
        return None
    try:
        content_length = int(str(value))
    except ValueError:
        return None
    return max(content_length, 0)


def _server_host(environ: WSGIEnvironment) -> str | None:
    server_name = _optional_string(environ.get("SERVER_NAME"))
    if server_name is None:
        return None
    server_port = _optional_string(environ.get("SERVER_PORT"))
    if server_port is None:
        return server_name
    return f"{server_name}:{server_port}"


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _run_async(coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future: Future[T] = executor.submit(lambda: asyncio.run(coroutine))
        return future.result()
