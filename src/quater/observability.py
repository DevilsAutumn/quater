"""Request correlation and structured access-log primitives."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TypeAlias
from uuid import uuid4

from quater.config import AppConfig
from quater.request import Request
from quater.response import Response
from quater.typing import RequestEntrypoint, RequestSource

AccessLogHook: TypeAlias = Callable[["AccessLogEvent"], Awaitable[None]]

_MAX_REQUEST_ID_LENGTH = 128


@dataclass(slots=True, frozen=True)
class AccessLogEvent:
    """Structured access-log event emitted after a server request.

    The event contains route-level metadata useful for logs and metrics. It
    does not include request bodies, request headers, or query-string values.
    """

    request_id: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    source: RequestSource
    entrypoint: RequestEntrypoint
    scheme: str
    client: str | None = None
    tool_name: str | None = None
    action_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "source": self.source,
            "entrypoint": self.entrypoint,
            "scheme": self.scheme,
            "client": self.client,
            "tool_name": self.tool_name,
            "action_name": self.action_name,
        }


def new_request_id() -> str:
    return uuid4().hex


def ensure_request_id(request: Request, config: AppConfig) -> str:
    request_id = _normalize_request_id(request.context.request_id)
    if request_id is not None:
        if request.context.request_id != request_id:
            request.context = replace(request.context, request_id=request_id)
        return request_id

    request_id = _incoming_request_id(request, config) or new_request_id()
    request.context = replace(request.context, request_id=request_id)
    return request_id


def add_request_id_header(
    response: Response,
    request: Request,
    config: AppConfig,
) -> Response:
    header_name = config.request_id_header
    request_id = request.context.request_id
    if header_name is None or request_id is None:
        return response

    response.headers = _set_header(response.headers, header_name, request_id)
    return response


def access_log_event(
    request: Request,
    response: Response,
    *,
    started_at: float,
) -> AccessLogEvent:
    return AccessLogEvent(
        request_id=request.context.request_id or new_request_id(),
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        duration_ms=(time.perf_counter() - started_at) * 1000,
        source=request.context.source,
        entrypoint=request.context.entrypoint,
        scheme=request.scheme,
        client=request.client,
        tool_name=request.context.tool_name,
        action_name=request.context.action_name,
    )


def _incoming_request_id(request: Request, config: AppConfig) -> str | None:
    header_name = config.request_id_header
    if header_name is None:
        return None
    return _normalize_request_id(request.headers.get(header_name))


def _normalize_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_REQUEST_ID_LENGTH:
        return None
    if not all(_valid_request_id_character(char) for char in stripped):
        return None
    return stripped


def _valid_request_id_character(char: str) -> bool:
    ordinal = ord(char)
    return 32 < ordinal < 127


def _set_header(
    headers: tuple[tuple[str, str], ...],
    name: str,
    value: str,
) -> tuple[tuple[str, str], ...]:
    normalized = name.lower()
    filtered = tuple(
        (header_name, header_value)
        for header_name, header_value in headers
        if header_name.lower() != normalized
    )
    return (*filtered, (name, value))


__all__ = [
    "AccessLogEvent",
    "AccessLogHook",
    "access_log_event",
    "add_request_id_header",
    "ensure_request_id",
    "new_request_id",
]
