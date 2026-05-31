---
title: Middleware and errors in Quater
description: Use before, after, and around middleware hooks, exception handlers, and safe error responses in Quater applications.
---

# Middleware And Errors

This page explains how Quater lets you run code around handlers and map
exceptions to responses.

## Prerequisites

Read [Routes and Handlers](/en/dev/routes-handlers). Middleware examples use
the public `Request` and `Response` objects.

## Middleware Types

Quater has three route middleware shapes:

- `before`: runs before route auth and binding.
- `after`: runs after the handler returns a response.
- `around`: wraps the handler pipeline.

Use middleware for cross-cutting behavior such as request IDs, timing headers,
audit logs, and tracing.

## Preferred: App-Wide Middleware

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


app.before_request(require_request_id)
app.after_response(add_request_id)
app.around_request(time_request)


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> JSONResponse:
    return JSONResponse({"order_id": order_id})
```

Use app-wide middleware for behavior that should apply consistently across the
application: request IDs, logging, timing, tracing, and default error mapping.

Missing header output:

```text
HTTP/1.1 400 Bad Request

Missing request id
```

## Middleware Or Resource?

If a handler needs a value, use a `Resource`. That keeps data loading,
authorization helpers, tenant lookup, and per-route validation visible in the
handler signature.

```python
from typing import Annotated

from quater import HTTPError, Request, Resource


async def verified_webhook_secret(request: Request) -> str:
    secret = request.headers.get("x-webhook-secret")
    if secret != "expected":
        raise HTTPError("Invalid webhook secret", status_code=401)
    return secret


WebhookSecret = Annotated[str, Resource(verified_webhook_secret)]


@app.post("/webhooks/payments")
async def payment_webhook(secret: WebhookSecret) -> dict[str, bool]:
    return {"ok": True}
```

Use middleware when you need to short-circuit before the handler, observe or
replace the response after the handler, or wrap the full handler execution.

## Route-Specific Middleware Hooks

You can attach middleware hooks to one route when the response or wrapper
behavior belongs only to that operation.

```python
async def add_export_headers(request: Request, response: Response) -> Response:
    response.headers = (
        *response.headers,
        ("content-disposition", 'attachment; filename="orders.csv"'),
    )
    return response


@app.get(
    "/exports/orders.csv",
    after=[add_export_headers],
)
async def export_orders() -> Response:
    return Response(b"id,total\nord_1001,42\n", content_type="text/csv")
```

Prefer app-wide middleware for cross-cutting behavior. Prefer `Resource`
injection when the handler needs a value. Use route-specific middleware hooks
for one-off response shaping, operation-specific wrapping, or temporary
instrumentation that should not affect other handlers.

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

Route-specific middleware and exception handlers take precedence over group
handlers. Group handlers take precedence over global handlers.

Middleware attached closer to the route runs with that route after group and
global configuration has been flattened at startup. For a matched route:

- global `before` runs before route-specific `before`.
- global `around` wraps route-specific `around`.
- route-specific `after` runs before global `after`.
- route-specific exception handlers run before global exception handlers.

## HTTP, MCP, And CLI

Global middleware and exception handlers wrap the real route handler on every
surface:

- HTTP requests run middleware around the matched HTTP route.
- MCP `tools/call` runs middleware around the tool's route handler, before the
  handler response is encoded into the JSON-RPC tool result.
- Local and remote CLI calls run middleware around the action's route handler,
  before the handler response is encoded into the CLI action payload.

For MCP and CLI calls, `after` and `around` middleware see the handler
`Response`, not the protocol envelope. A timing middleware sees `/orders/123`
and the handler's status code, not `/mcp` or `/__quater__/actions/call`.

This is a behavior change if you used global middleware that assumes every
request is an HTTP browser/API response. Cookies, redirects, HTML error pages,
and HTTP security headers can be a poor fit for MCP or CLI tool results. Until
Quater has surface-aware middleware opt-outs, check `request.context.source`
inside global middleware and no-op for `"mcp"` or `"cli"` when the behavior only
makes sense for HTTP.

## What Can Go Wrong

`Cannot register middleware after routes are compiled`
: Register global middleware before startup, tests, or the first request.

`Route handlers must be async functions`
: Middleware and exception handlers that Quater calls should use `async def`.

`500 Internal Server Error`
: An exception reached Quater without a matching exception handler. In
development, enable `debug=True` to see more detail.

## Also See

- [Public API](/en/dev/api): compact API overview.
- [Application Reference](/en/dev/reference/application): exact middleware
  and exception handler signatures.
- [Testing](/en/dev/testing): test middleware and error paths in process.
