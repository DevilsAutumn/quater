from __future__ import annotations

from collections.abc import Awaitable, Callable

from quater import Quater, Request, Response, RouteGroup

app = Quater()
group = RouteGroup(prefix="/api")


@app.get("/users/{id:int}")
async def get_user(id: int) -> dict[str, int]:
    return {"id": id}


@app.post("/users")
async def create_user(request: Request) -> Response:
    return await app.handle(request)


@group.get("/health")
async def grouped_health() -> dict[str, bool]:
    return {"ok": True}


app.include(group)

get_user_handler: Callable[[int], Awaitable[dict[str, int]]] = get_user
create_user_handler: Callable[[Request], Awaitable[Response]] = create_user
grouped_handler: Callable[[], Awaitable[dict[str, bool]]] = grouped_health
