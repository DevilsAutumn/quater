from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import assert_type

from quater import Quater, Request, Response

app = Quater()


@app.before_request
async def before(request: Request) -> Response | None:
    return None


@app.before_request(surfaces=["api"])
async def before_api(request: Request) -> Response | None:
    return None


@app.after_response
async def after(request: Request, response: Response) -> Response:
    return response


@app.after_response(surfaces=["mcp", "cli"])
async def after_agents(request: Request, response: Response) -> Response:
    return response


@app.around_request
async def around(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    return await call_next(request)


@app.around_request(surfaces=["cli"])
async def around_cli(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    return await call_next(request)


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: Exception) -> Response | None:
    return None


@app.exception_handler(RuntimeError, surfaces=["mcp"])
async def handle_mcp_runtime_error(
    request: Request,
    exc: Exception,
) -> Response | None:
    return None


assert_type(before, Callable[[Request], Awaitable[Response | None]])
assert_type(before_api, Callable[[Request], Awaitable[Response | None]])
assert_type(after, Callable[[Request, Response], Awaitable[Response]])
assert_type(after_agents, Callable[[Request, Response], Awaitable[Response]])
assert_type(
    around,
    Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]],
)
assert_type(
    around_cli,
    Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]],
)
assert_type(
    handle_value_error,
    Callable[[Request, Exception], Awaitable[Response | None]],
)
assert_type(
    handle_mcp_runtime_error,
    Callable[[Request, Exception], Awaitable[Response | None]],
)
