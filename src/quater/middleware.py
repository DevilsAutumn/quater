"""Middleware pipeline primitives."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import TypeAlias

from quater._finalize import move_response_finalizers
from quater.exceptions import ConfigurationError, HTTPError
from quater.request import Request
from quater.response import Response, TextResponse
from quater.typing import SURFACES, RequestSource

RequestHandler: TypeAlias = Callable[[Request], Awaitable[Response]]
RouteHandler: TypeAlias = Callable[[Request, Mapping[str, object]], Awaitable[Response]]
BeforeMiddleware: TypeAlias = Callable[[Request], Awaitable[Response | None]]
AfterMiddleware: TypeAlias = Callable[[Request, Response], Awaitable[Response]]
AroundMiddleware: TypeAlias = Callable[[Request, RequestHandler], Awaitable[Response]]
ExceptionMiddleware: TypeAlias = Callable[
    [Request, Exception],
    Awaitable[Response | None],
]
_ERROR_LOGGER = logging.getLogger("quater.error")
_SURFACE_SET: frozenset[RequestSource] = frozenset(SURFACES)
ScopedSurfaces: TypeAlias = tuple[RequestSource, ...] | None


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


def normalize_middleware_surfaces(
    surfaces: Iterable[str] | None,
) -> ScopedSurfaces:
    if surfaces is None:
        return None
    if isinstance(surfaces, str):
        raise ConfigurationError(
            "Middleware surfaces must be a list of surface names, not a string"
        )

    normalized: list[RequestSource] = []
    seen: set[str] = set()
    for surface in surfaces:
        if surface not in _SURFACE_SET:
            raise ConfigurationError(
                f"Unknown middleware surface {surface!r}; expected one of "
                f"{', '.join(SURFACES)}"
            )
        if surface in seen:
            raise ConfigurationError(
                f"Middleware lists surface {surface!r} more than once"
            )
        seen.add(surface)
        normalized.append(surface)
    if not normalized:
        raise ConfigurationError("Middleware must cover at least one surface")
    return tuple(normalized)


def before_middleware_for_surfaces(
    middleware: BeforeMiddleware,
    surfaces: ScopedSurfaces,
) -> BeforeMiddleware:
    if surfaces is None:
        return middleware

    @wraps(middleware)
    async def scoped(request: Request) -> Response | None:
        if request.context.source not in surfaces:
            return None
        return await middleware(request)

    return scoped


def after_middleware_for_surfaces(
    middleware: AfterMiddleware,
    surfaces: ScopedSurfaces,
) -> AfterMiddleware:
    if surfaces is None:
        return middleware

    @wraps(middleware)
    async def scoped(request: Request, response: Response) -> Response:
        if request.context.source not in surfaces:
            return response
        return await middleware(request, response)

    return scoped


def around_middleware_for_surfaces(
    middleware: AroundMiddleware,
    surfaces: ScopedSurfaces,
) -> AroundMiddleware:
    if surfaces is None:
        return middleware

    @wraps(middleware)
    async def scoped(request: Request, call_next: RequestHandler) -> Response:
        if request.context.source not in surfaces:
            return await call_next(request)
        return await middleware(request, call_next)

    return scoped


def exception_handler_for_surfaces(
    handler: ExceptionMiddleware,
    surfaces: ScopedSurfaces,
) -> ExceptionMiddleware:
    if surfaces is None:
        return handler

    @wraps(handler)
    async def scoped(request: Request, exc: Exception) -> Response | None:
        if request.context.source not in surfaces:
            return None
        return await handler(request, exc)

    return scoped


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
            response = await _resolve_pipeline_exception(
                request,
                exc,
                exception_handlers,
                debug=debug,
                handle_unhandled=handle_unhandled_exceptions,
            )
            if response is None:
                raise

        response = await _close_function_resources_before_response(
            request,
            response,
            exception_handlers,
            debug=debug,
            handle_unhandled=handle_unhandled_exceptions,
        )

        try:
            for after_middleware in after:
                response = await after_middleware(request, response)
        except Exception as exc:
            response = await _resolve_pipeline_exception(
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


async def _resolve_pipeline_exception(
    request: Request,
    exc: Exception,
    handlers: tuple[ExceptionHandlerEntry, ...],
    *,
    debug: bool,
    handle_unhandled: bool,
) -> Response | None:
    await request._aexit_resources_for_error(exc)
    return await _resolve_exception(
        request,
        exc,
        handlers,
        debug=debug,
        handle_unhandled=handle_unhandled,
    )


async def _close_function_resources_before_response(
    request: Request,
    response: Response,
    handlers: tuple[ExceptionHandlerEntry, ...],
    *,
    debug: bool,
    handle_unhandled: bool,
) -> Response:
    try:
        await request._aclose_function_resources()
    except Exception as exc:
        resolved = await _resolve_pipeline_exception(
            request,
            exc,
            handlers,
            debug=debug,
            handle_unhandled=handle_unhandled,
        )
        if resolved is None:
            raise
        return move_response_finalizers(response, resolved)
    return response


def default_exception_response(exc: Exception, *, debug: bool) -> Response:
    if isinstance(exc, HTTPError):
        return TextResponse(exc.detail, status_code=exc.status_code)
    _log_unhandled_exception(exc)
    if debug:
        return TextResponse(
            f"{type(exc).__name__}: {exc}",
            status_code=500,
        )
    return TextResponse("Internal Server Error", status_code=500)


def _log_unhandled_exception(exc: Exception) -> None:
    _ERROR_LOGGER.error(
        "Unhandled exception while processing request",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
