"""Internal request and response cleanup callbacks."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from quater.request import Request
from quater.response import Response

Finalizer = Callable[[], Awaitable[None]]
ResponseT = TypeVar("ResponseT", bound=Response)

_logger = logging.getLogger("quater.finalize")


def add_request_finalizer(request: Request, finalizer: Finalizer) -> None:
    if request._finalizers is None:
        request._finalizers = []
    request._finalizers.append(finalizer)


def move_request_finalizers_to_response(
    request: Request,
    response: ResponseT,
) -> ResponseT:
    finalizers = request._finalizers
    if not finalizers:
        return response
    request._finalizers = None
    _add_response_finalizers(response, finalizers)
    return response


def move_response_finalizers(
    source: Response,
    target: ResponseT,
) -> ResponseT:
    finalizers = source._finalizers
    if not finalizers:
        return target
    source._finalizers = None
    _add_response_finalizers(target, finalizers)
    return target


async def run_response_finalizers(response: Response) -> None:
    finalizers = response._finalizers
    if not finalizers:
        return
    response._finalizers = None
    for finalizer in reversed(finalizers):
        try:
            await finalizer()
        except Exception:
            _logger.exception("Response cleanup failed")


async def close_request_finalizers(request: Request) -> None:
    finalizers = request._finalizers
    if not finalizers:
        return
    request._finalizers = None
    for finalizer in reversed(finalizers):
        await finalizer()


def _add_response_finalizers(
    response: Response,
    finalizers: list[Finalizer],
) -> None:
    if response._finalizers is None:
        response._finalizers = []
    response._finalizers.extend(finalizers)


__all__ = [
    "add_request_finalizer",
    "close_request_finalizers",
    "move_request_finalizers_to_response",
    "move_response_finalizers",
    "run_response_finalizers",
]
