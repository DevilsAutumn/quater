# Resources, State, And Testing

Use `app.state` for long-lived objects. Use `Resource` for request-scoped
dependencies.

Full docs:

- Resources and state: https://quater.devilsautumn.com/en/stable/resources
- Testing: https://quater.devilsautumn.com/en/stable/testing
- Resources reference: https://quater.devilsautumn.com/en/stable/reference/resources
- Testing reference: https://quater.devilsautumn.com/en/stable/reference/testing

## State

Initialize shared objects in lifespan hooks:

```python
from quater import Quater, Request

app = Quater()


@app.on_startup
async def startup() -> None:
    app.state.cache = {}


@app.on_shutdown
async def shutdown() -> None:
    app.state.cache.clear()
```

Use `request.state` for per-request values set by middleware.

## Resources

Declare explicit resources with `Resource` and inject them by handler parameter
name:

```python
from collections.abc import AsyncIterator

from quater import Request, Resource


async def session_resource(request: Request) -> AsyncIterator[DatabaseSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


db_session = Resource(session_resource)


@app.get("/orders/{order_id}", inject={"session": db_session})
async def get_order(order_id: str, session: DatabaseSession) -> dict[str, object]:
    ...
```

Injected parameters are not caller inputs. They should not appear in OpenAPI,
MCP schemas, or CLI action schemas.

`Resource` carries the provider's resolved value type. When auth or middleware
needs to open a request-scoped resource manually, prefer the raw resource:

```python
async def authenticate(request: Request):
    session = await request.resolve(db_session)
    ...
```

Keep `Annotated[T, db_session]` for handler/resource-provider injection. It is
still accepted by `request.resolve()` for compatibility, but the raw
`Resource[T]` path is the typed no-cast form.

## Testing HTTP

Use `TestClient` to exercise the Quater request path without opening a port:

```python
import pytest

from quater import Quater, TestClient


@pytest.mark.asyncio
async def test_health() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

`TestClient` supports `json=`, `content=`, `data=`, and `files=`.

## Testing MCP

Use `client.mcp` for tool calls:

```python
response = await TestClient(app).mcp.tools_call(
    "get_order",
    {"order_id": "ord_1001"},
    token="demo-token",
)
```

Test auth denial, missing arguments, and tool schemas. Do not call private MCP
internals directly unless testing Quater itself.
