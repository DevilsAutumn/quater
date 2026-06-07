# App Patterns

Use public imports from `quater`.

Full docs:

- Routes and handlers: https://quater.devilsautumn.com/en/stable/routes-handlers
- Application reference: https://quater.devilsautumn.com/en/stable/reference/application
- Parameter reference: https://quater.devilsautumn.com/en/stable/reference/parameters

```python
from quater import Quater

app = Quater()
```

## Routes

Handlers must be async functions:

```python
@app.get("/orders/{order_id}", description="Fetch one order.")
async def get_order(order_id: str) -> dict[str, str]:
    return {"order_id": order_id}
```

Use `RouteGroup` for shared prefixes, auth, resources, or middleware. Quater
flattens groups at startup.

## Binding

Binding order:

1. `inject={...}` resources
2. `Request`
3. explicit markers
4. route path names
5. scalar query parameters
6. JSON body parameters

Use markers when the source is not obvious:

```python
from quater import Body, Header, Path, Query


async def update_order(
    order_id: str = Path(alias="id"),
    payload: UpdateOrder = Body(),
    include_events: bool = Query(default=False, alias="include-events"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> dict[str, object]:
    ...
```

## JSON, Forms, And Files

Use `msgspec.Struct` for typed JSON bodies:

```python
import msgspec


class UpdateOrder(msgspec.Struct):
    status: str
```

Use `Form` for scalar form fields and `File` for multipart uploads:

```python
from quater import File, Form, UploadFile


async def import_document(
    account_id: str = Form(),
    document: UploadFile = File(),
) -> dict[str, object]:
    content = await document.read()
    return {"account_id": account_id, "size": len(content)}
```

Do not combine JSON `Body` with `Form` or `File` in one route.

## Responses

Plain return values are enough for most handlers:

- `dict`, `list`, dataclass, and `msgspec.Struct` become JSON.
- `str` becomes text.
- `bytes` becomes bytes.
- `None` becomes `204 No Content`.
- `Response` subclasses pass through.

Use explicit response classes for status codes, redirects, HTML, bytes, or
streams.

## Config And Limits

Use constructor options for app-level config:

```python
app = Quater(
    allowed_hosts=["api.example.com"],
    max_body_size="10mb",
    max_file_size="5mb",
)
```

Deployment can also set limit defaults with environment variables such as
`QUATER_MAX_BODY_SIZE`, `QUATER_MAX_FILE_SIZE`, and
`QUATER_MAX_ACTION_RESPONSE_SIZE`. Explicit constructor options override env
values.
