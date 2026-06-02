"""ASGI adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any, Literal, TypeAlias, cast
from urllib.parse import unquote_to_bytes

from quater._finalize import run_response_finalizers
from quater.adapters._shared import (
    QuaterApplication,
    as_latin1_header_bytes,
    first_client_address,
    iter_response_body,
    request_from_parts,
)
from quater.exceptions import BadRequestError, PayloadTooLargeError
from quater.request import BodyReader

ASGIMessage: TypeAlias = MutableMapping[str, Any]
ASGIReceive: TypeAlias = Callable[[], Awaitable[ASGIMessage]]
ASGISend: TypeAlias = Callable[[Mapping[str, Any]], Awaitable[None]]
ASGIScope: TypeAlias = Mapping[str, Any]
LifespanSuccess: TypeAlias = Literal[
    "lifespan.startup.complete",
    "lifespan.shutdown.complete",
]
LifespanFailure: TypeAlias = Literal[
    "lifespan.startup.failed",
    "lifespan.shutdown.failed",
]


class ASGIAdapter:
    """ASGI 3.0 callable for a Quater app."""

    __slots__ = ("_app",)

    def __init__(self, app: QuaterApplication) -> None:
        self._app = app

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        scope_type = scope.get("type")
        if scope_type == "http":
            await self._handle_http(scope, receive, send)
            return
        if scope_type == "lifespan":
            await self._handle_lifespan(receive, send)
            return
        if scope_type == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 1003,
                    "reason": "WebSocket support is not enabled",
                }
            )
            return
        raise ValueError(f"Unsupported ASGI scope type: {scope_type!r}")

    async def _handle_http(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        request = request_from_parts(
            method=str(scope["method"]),
            path=_path_from_scope(scope),
            scheme=str(scope.get("scheme", "http")),
            headers=tuple(
                _decode_header_pair(pair) for pair in scope.get("headers", ())
            ),
            query_string=cast(str | bytes, scope.get("query_string", b"")),
            body=_body_reader(receive, self._app.config.max_body_size),
            client=first_client_address(scope.get("client")),
        )
        response = await self._app.handle(request)
        try:
            headers = as_latin1_header_bytes(response.headers)

            await send(
                {
                    "type": "http.response.start",
                    "status": response.status_code,
                    "headers": headers,
                }
            )

            if not response.is_streaming:
                await send(
                    {
                        "type": "http.response.body",
                        "body": response.body,
                        "more_body": False,
                    }
                )
                return

            chunks_sent = False
            async for chunk in iter_response_body(response):
                chunks_sent = True
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    }
                )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"" if chunks_sent else response.body,
                    "more_body": False,
                }
            )
        finally:
            await run_response_finalizers(response)

    async def _handle_lifespan(
        self,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "lifespan.startup":
                await self._run_lifespan_event(
                    self._app.startup,
                    send,
                    success_type="lifespan.startup.complete",
                    failure_type="lifespan.startup.failed",
                )
                continue
            if message_type == "lifespan.shutdown":
                await self._run_lifespan_event(
                    self._app.shutdown,
                    send,
                    success_type="lifespan.shutdown.complete",
                    failure_type="lifespan.shutdown.failed",
                )
                return
            raise ValueError(f"Unsupported ASGI lifespan message: {message_type!r}")

    async def _run_lifespan_event(
        self,
        hook: Callable[[], Awaitable[None]],
        send: ASGISend,
        *,
        success_type: LifespanSuccess,
        failure_type: LifespanFailure,
    ) -> None:
        try:
            await hook()
        except Exception as exc:
            await send({"type": failure_type, "message": str(exc)})
            return
        await send({"type": success_type})


def _decode_header_pair(pair: tuple[bytes, bytes] | tuple[str, str]) -> tuple[str, str]:
    name, value = pair
    return (_decode_header_part(name), _decode_header_part(value))


def _decode_header_part(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return value


def _path_from_scope(scope: ASGIScope) -> str:
    fallback = str(scope.get("path", "/") or "/")
    raw_path = scope.get("raw_path")
    if not isinstance(raw_path, bytes) or not raw_path:
        return fallback

    path_bytes = raw_path.split(b"?", 1)[0]
    if not path_bytes.startswith(b"/"):
        return fallback
    try:
        path = unquote_to_bytes(path_bytes).decode("utf-8")
    except UnicodeDecodeError:
        return fallback
    return path if path.startswith("/") else fallback


async def _read_body(receive: ASGIReceive, max_body_size: int) -> bytes:
    chunks: list[bytes] = []
    body_size = 0
    while True:
        message = await receive()
        message_type = message.get("type")
        if message_type == "http.disconnect":
            raise BadRequestError(
                "Client disconnected before request body was complete"
            )
        if message_type != "http.request":
            raise ValueError(f"Unsupported ASGI HTTP message: {message_type!r}")
        body = message.get("body", b"")
        if body:
            chunk = cast(bytes, body)
            body_size += len(chunk)
            if body_size > max_body_size:
                raise PayloadTooLargeError
            chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _body_reader(receive: ASGIReceive, max_body_size: int) -> BodyReader:
    async def read() -> bytes:
        return await _read_body(receive, max_body_size)

    return read
