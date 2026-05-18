# Routes And Handlers

This page explains how Quater routes map incoming calls to your application
code.

## Prerequisites

Read [Quickstart](/en/latest/quickstart). You should know what an async Python
function is.

## What A Route Means In Quater

A route is the public declaration of one backend operation. It gives Quater the
method, path, description, auth policy, resource requirements, middleware, and
optional agent or CLI exposure.

The handler is still plain Python:

```python
from quater import HTTPError, Quater

app = Quater()

ORDERS: dict[str, dict[str, object]] = {
    "ord_1001": {"id": "ord_1001", "status": "paid"}
}


@app.get("/orders/{order_id}", description="Fetch one order.")
async def get_order(order_id: str) -> dict[str, object]:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPError("Order not found", status_code=404)
    return order
```

Expected response:

```json
{
  "id": "ord_1001",
  "status": "paid"
}
```

## Binding Rules

Quater binds handler parameters from explicit sources first, then from the route
shape:

1. resources declared with `inject={...}`
2. the current `Request`
3. `Path`, `Query`, `Body`, `Form`, `File`, `Header`, or `Cookie` markers
4. path parameters from the route pattern
5. scalar query parameters
6. one JSON body parameter

Use markers when a reader should not have to guess:

```python
import msgspec

from quater import Body, Header, Path, Query, Quater


class UpdateOrder(msgspec.Struct):
    status: str
    notify_customer: bool = False


app = Quater()


@app.patch("/orders/{id}", description="Update one order.")
async def update_order(
    order_id: str = Path(alias="id", description="Order id."),
    payload: UpdateOrder = Body(description="New order state."),
    include_events: bool = Query(default=False, alias="include-events"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "status": payload.status,
        "include_events": include_events,
        "request_id": request_id,
    }
```

Use form and file markers for non-JSON request bodies:

```python
from quater import File, Form, Quater, UploadFile

app = Quater()


@app.post("/imports", description="Import one CSV file.")
async def import_orders(
    account_id: str = Form(),
    document: UploadFile = File(description="CSV document."),
) -> dict[str, object]:
    content = await document.read()
    return {
        "account_id": account_id,
        "filename": document.filename,
        "size": len(content),
    }
```

Routes with `File` parameters are HTTP-only in this release. Quater rejects
`tool=True` or `cli=True` on those routes so agents and CLI callers do not get a
fake file-upload contract.

## Route Groups

Use `RouteGroup` when a feature has a shared prefix, auth policy, middleware, or
resources. Quater flattens groups when routes compile, so groups do not add a
second router on every request.

```python
from quater import Quater, RouteGroup

app = Quater()
orders = RouteGroup(prefix="/orders")


@orders.get("/{order_id}", description="Fetch one order.")
async def get_order(order_id: str) -> dict[str, str]:
    return {"order_id": order_id}


app.include(orders)
```

## What Can Go Wrong

`Route handlers must be async functions`
: Declare handlers with `async def`.

`Path parameter 'order_id' does not match route path`
: Rename the handler parameter or use `Path(alias=...)`.

`Only one body parameter is supported`
: Move body fields into one `msgspec.Struct`.

`JSON body parameters cannot be combined with form or file parameters`
: One handler reads one request body format. Split the route or pick one input
  shape.

`Dynamic routes at the same position must use the same name and converter`
: Keep conflicting route patterns consistent, or split the paths.

## Also See

- [Parameters Reference](/en/latest/reference/parameters): exact marker
  signatures.
- [HTTP, MCP, and CLI Surfaces](/en/latest/surfaces): how one route can opt into
  other access paths.
- [Resources and State](/en/latest/resources): inject values that should never
  come from the caller.
