"""Granian RSGI adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Iterable
from typing import Protocol, TypeAlias, cast

from quater._finalize import run_response_finalizers
from quater.adapters._shared import (
    QuaterApplication,
    first_client_address,
    iter_response_body,
    request_from_parts,
    response_headers,
)
from quater.exceptions import PayloadTooLargeError
from quater.request import BodyReader

RSGICallbackResult: TypeAlias = Awaitable[None] | tuple[int, bool] | None


class RSGIHeaders(Protocol):
    def items(self) -> list[tuple[str, str]]: ...


class RSGIScope(Protocol):
    proto: str
    method: str
    path: str
    query_string: str
    scheme: str
    client: str
    authority: str | None

    @property
    def headers(self) -> RSGIHeaders: ...


class RSGIHTTPStreamTransport(Protocol):
    async def send_bytes(self, data: bytes) -> None: ...


class RSGIHTTPProtocol(Protocol):
    async def __call__(self) -> bytes: ...

    def __aiter__(self) -> AsyncIterator[bytes]: ...

    def response_empty(self, status: int, headers: list[tuple[str, str]]) -> None: ...

    def response_bytes(
        self,
        status: int,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> None: ...

    def response_stream(
        self,
        status: int,
        headers: list[tuple[str, str]],
    ) -> RSGIHTTPStreamTransport: ...


class RSGIWebSocketProtocol(Protocol):
    def close(self, status: int | None) -> tuple[int, bool]: ...


class RSGIAdapter:
    """RSGI callable for Granian's primary HTTP path."""

    __slots__ = ("_app",)

    def __init__(self, app: QuaterApplication) -> None:
        self._app = app

    def __call__(
        self,
        scope: RSGIScope,
        protocol: RSGIHTTPProtocol | RSGIWebSocketProtocol,
    ) -> RSGICallbackResult:
        if scope.proto == "http":
            return self._handle_http(scope, cast(RSGIHTTPProtocol, protocol))
        return cast(RSGIWebSocketProtocol, protocol).close(1003)

    async def _handle_http(
        self,
        scope: RSGIScope,
        protocol: RSGIHTTPProtocol,
    ) -> None:
        headers = tuple(scope.headers.items())
        if scope.authority is not None:
            if _has_header(headers, "host"):
                headers = (*headers, (":authority", scope.authority))
            else:
                headers = (*headers, ("host", scope.authority))

        request = request_from_parts(
            method=scope.method,
            path=scope.path,
            scheme=scope.scheme,
            headers=headers,
            query_string=scope.query_string,
            body=_body_reader(protocol, self._app.config.max_body_size),
            client=first_client_address(scope.client),
        )
        response = await self._app.handle(request)
        try:
            response_header_list = response_headers(response)

            if response.is_streaming:
                transport = protocol.response_stream(
                    response.status_code,
                    response_header_list,
                )
                async for chunk in iter_response_body(response):
                    await transport.send_bytes(chunk)
                return

            if response.body:
                protocol.response_bytes(
                    response.status_code,
                    response_header_list,
                    response.body,
                )
                return

            protocol.response_empty(response.status_code, response_header_list)
        finally:
            await run_response_finalizers(response)


def _body_reader(protocol: RSGIHTTPProtocol, max_body_size: int) -> BodyReader:
    async def read() -> bytes:
        return await _read_body(protocol, max_body_size)

    return read


async def _read_body(protocol: RSGIHTTPProtocol, max_body_size: int) -> bytes:
    chunks: list[bytes] = []
    body_size = 0
    async for chunk in protocol:
        if not chunk:
            continue
        body_size += len(chunk)
        if body_size > max_body_size:
            raise PayloadTooLargeError
        chunks.append(chunk)

    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]
    return b"".join(chunks)


def _has_header(headers: Iterable[tuple[str, str]], name: str) -> bool:
    normalized = name.lower()
    return any(header_name.lower() == normalized for header_name, _ in headers)
