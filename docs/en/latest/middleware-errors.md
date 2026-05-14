# Middleware And Errors

This page explains how Quater lets you run code around handlers and map
exceptions to responses.

## Prerequisites

Read [Routes and Handlers](/en/latest/routes-handlers). Middleware examples use
the public `Request` and `Response` objects.

## Middleware Types

Quater has three route middleware shapes:

- `before`: runs before route auth and binding.
- `after`: runs after the handler returns a response.
- `around`: wraps the handler pipeline.

Use middleware for cross-cutting behavior such as request IDs, timing headers,
audit logs, and tracing.

## A Runnable Example

```python
from collections.abc import Awaitable, Callable
from time import perf_counter

from quater import JSONResponse, Quater, Request, Response, TextResponse


app = Quater()


async def require_request_id(request: Request) -> Response | None:
    request_id = request.headers.get("x-request-id")
    if request_id is None:
        return TextResponse("Missing request id", status_code=400)
    request.state.request_id = request_id
    return None


async def add_request_id(request: Request, response: Response) -> Response:
    response.headers = (*response.headers, ("x-request-id", request.state.request_id))
    return response


async def time_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    start = perf_counter()
    response = await call_next(request)
    elapsed_ms = f"{(perf_counter() - start) * 1000:.2f}"
    response.headers = (*response.headers, ("x-elapsed-ms", elapsed_ms))
    return response


@app.get(
    "/orders/{order_id}",
    before=[require_request_id],
    after=[add_request_id],
    around=[time_request],
)
async def get_order(order_id: str) -> JSONResponse:
    return JSONResponse({"order_id": order_id})
```

Missing header output:

```text
HTTP/1.1 400 Bad Request

Missing request id
```

## Exception Handlers

Exception handlers map exception classes to responses without adding
`try`/`except` to every handler.

```python
from quater import JSONResponse, Quater, Request


class OrderNotFound(Exception):
    pass


app = Quater()


@app.exception_handler(OrderNotFound)
async def handle_order_not_found(
    request: Request,
    exc: OrderNotFound,
) -> JSONResponse:
    return JSONResponse({"error": "order_not_found"}, status_code=404)


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> dict[str, str]:
    raise OrderNotFound(order_id)
```

Expected response:

```json
{
  "error": "order_not_found"
}
```

## Ordering

Route-level handlers take precedence over group handlers. Group handlers take
precedence over global handlers.

Middleware attached closer to the route runs with that route after group and
global configuration has been flattened at startup.

## What Can Go Wrong

`Cannot register middleware after routes are compiled`
: Register global middleware before startup, tests, or the first request.

`Route handlers must be async functions`
: Middleware and exception handlers that Quater calls should use `async def`.

`500 Internal Server Error`
: An exception reached Quater without a matching exception handler. In
development, enable `debug=True` to see more detail.

## Also See

- [Public API](/en/latest/api): compact API overview.
- [Application Reference](/en/latest/reference/application): exact middleware
  and exception handler signatures.
- [Testing](/en/latest/testing): test middleware and error paths in process.
