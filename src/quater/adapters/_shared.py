"""Shared adapter helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from http import HTTPStatus
from typing import Protocol

from quater.config import AppConfig
from quater.datastructures import HeaderItems
from quater.request import Request, RequestBody
from quater.response import (
    Response,
    StreamResponse,
    validate_response,
    validate_stream_chunk,
)


class QuaterApplication(Protocol):
    config: AppConfig

    async def handle(self, request: Request) -> Response: ...

    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...


def response_headers(response: Response) -> list[tuple[str, str]]:
    validate_response(response)
    return list(response.headers)


def response_status(status_code: int) -> str:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "Unknown"
    return f"{status_code} {phrase}"


async def iter_response_body(response: Response) -> AsyncIterator[bytes]:
    validate_response(response)
    if isinstance(response, StreamResponse):
        async for chunk in response.body_iterator:
            body = validate_stream_chunk(chunk)
            if body:
                yield body
        return
    if response.body:
        yield response.body


async def collect_response_body(response: Response) -> list[bytes]:
    return [chunk async for chunk in iter_response_body(response)]


def request_from_parts(
    *,
    method: str,
    path: str,
    scheme: str,
    headers: HeaderItems | Mapping[str, str],
    query_string: str | bytes,
    body: RequestBody,
    client: str | None,
) -> Request:
    return Request(
        method=method,
        path=path,
        scheme=scheme,
        headers=headers,
        query_string=query_string,
        body=body,
        client=client,
    )


def first_client_address(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, tuple | list):
        if not value:
            return None
        first = value[0]
        return str(first) if first is not None else None

    text = str(value)
    if not text:
        return None
    if text.startswith("["):
        closing = text.find("]")
        if closing != -1:
            return text[1:closing]
    if text.count(":") == 1:
        host, port = text.rsplit(":", 1)
        if port.isdigit():
            return host
    return text


def as_latin1_header_bytes(
    headers: Iterable[tuple[str, str]],
) -> list[tuple[bytes, bytes]]:
    return [
        (name.encode("latin-1"), value.encode("latin-1")) for name, value in headers
    ]
