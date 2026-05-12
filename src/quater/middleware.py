"""Middleware pipeline primitives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from quater.exceptions import HTTPError
from quater.request import Request
from quater.response import Response, TextResponse

RequestHandler: TypeAlias = Callable[[Request], Awaitable[Response]]
RouteHandler: TypeAlias = Callable[[Request, Mapping[str, object]], Awaitable[Response]]
BeforeMiddleware: TypeAlias = Callable[[Request], Awaitable[Response | None]]
AfterMiddleware: TypeAlias = Callable[[Request, Response], Awaitable[Response]]
AroundMiddleware: TypeAlias = Callable[[Request, RequestHandler], Awaitable[Response]]
ExceptionMiddleware: TypeAlias = Callable[
    [Request, Exception],
    Awaitable[Response | None],
]


class ExceptionHandler(Protocol):
    """Callable registered for one exception type."""

    async def __call__(self, request: Request, exc: Exception) -> Response | None:
        """Return a response, or None to let another handler try."""


@dataclass(slots=True, frozen=True)
class ExceptionHandlerEntry:
    exception_type: type[Exception]
    handler: ExceptionMiddleware


@dataclass(slots=True, frozen=True)
class MiddlewareStack:
    before: tuple[BeforeMiddleware, ...] = ()
    after: tuple[AfterMiddleware, ...] = ()
    around: tuple[AroundMiddleware, ...] = ()
    exception_handlers: tuple[ExceptionHandlerEntry, ...] = ()

    @classmethod
    def from_parts(
        cls,
        *,
        before: Iterable[BeforeMiddleware] = (),
        after: Iterable[AfterMiddleware] = (),
        around: Iterable[AroundMiddleware] = (),
        exception_handlers: Iterable[ExceptionHandlerEntry] = (),
    ) -> MiddlewareStack:
        return cls(
            before=tuple(before),
            after=tuple(after),
            around=tuple(around),
            exception_handlers=tuple(exception_handlers),
        )


def merge_middleware_stack(
    parent: MiddlewareStack,
    child: MiddlewareStack,
) -> MiddlewareStack:
    """Merge group middleware into child route middleware."""

    return MiddlewareStack(
        before=(*parent.before, *child.before),
        after=(*child.after, *parent.after),
        around=(*parent.around, *child.around),
        exception_handlers=(
            *child.exception_handlers,
            *parent.exception_handlers,
        ),
    )


def compile_middleware_pipeline(
    endpoint: RouteHandler,
    *,
    global_stack: MiddlewareStack,
    route_stack: MiddlewareStack,
    debug: bool,
    handle_unhandled_exceptions: bool = True,
) -> RouteHandler:
    before = (*global_stack.before, *route_stack.before)
    after = (*route_stack.after, *global_stack.after)
    around = (*global_stack.around, *route_stack.around)
    exception_handlers = (
        *route_stack.exception_handlers,
        *global_stack.exception_handlers,
    )

    async def call_endpoint(
        request: Request,
        path_params: Mapping[str, object],
    ) -> Response:
        response: Response | None = None
        try:
            for middleware in before:
                response = await middleware(request)
                if response is not None:
                    break

            if response is None:
                response = await _call_around(
                    endpoint,
                    around,
                    request,
                    path_params,
                )
        except Exception as exc:
            response = await _resolve_exception(
                request,
                exc,
                exception_handlers,
                debug=debug,
                handle_unhandled=handle_unhandled_exceptions,
            )
            if response is None:
                raise

        try:
            for after_middleware in after:
                response = await after_middleware(request, response)
        except Exception as exc:
            response = await _resolve_exception(
                request,
                exc,
                exception_handlers,
                debug=debug,
                handle_unhandled=handle_unhandled_exceptions,
            )
            if response is None:
                raise

        return response

    return call_endpoint


async def _call_around(
    endpoint: RouteHandler,
    around: tuple[AroundMiddleware, ...],
    request: Request,
    path_params: Mapping[str, object],
) -> Response:
    async def call_leaf(next_request: Request) -> Response:
        return await endpoint(next_request, path_params)

    handler = call_leaf
    for middleware in reversed(around):
        next_handler = handler

        async def call_next(
            next_request: Request,
            *,
            current: AroundMiddleware = middleware,
            next_: RequestHandler = next_handler,
        ) -> Response:
            return await current(next_request, next_)

        handler = call_next

    return await handler(request)


async def _resolve_exception(
    request: Request,
    exc: Exception,
    handlers: tuple[ExceptionHandlerEntry, ...],
    *,
    debug: bool,
    handle_unhandled: bool,
) -> Response | None:
    for entry in handlers:
        if not isinstance(exc, entry.exception_type):
            continue
        try:
            response = await entry.handler(request, exc)
        except Exception as handler_error:
            if not handle_unhandled:
                raise
            return default_exception_response(handler_error, debug=debug)
        if response is not None:
            return response

    if not handle_unhandled:
        return None
    return default_exception_response(exc, debug=debug)


def default_exception_response(exc: Exception, *, debug: bool) -> Response:
    if isinstance(exc, HTTPError):
        return TextResponse(exc.detail, status_code=exc.status_code)
    if debug:
        return TextResponse(
            f"{type(exc).__name__}: {exc}",
            status_code=500,
        )
    return TextResponse("Internal Server Error", status_code=500)
