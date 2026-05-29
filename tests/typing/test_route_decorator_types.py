from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from quater import Quater, Request, Resource, Response, RouteGroup

app = Quater()
group = RouteGroup(prefix="/api")


async def db_resource() -> str:
    return "db"


db = Resource(db_resource)


@app.get("/users/{id:int}")
async def get_user(id: int) -> dict[str, int]:
    return {"id": id}


@app.post("/users")
async def create_user(request: Request) -> Response:
    return await app.handle(request)


@group.get("/health")
async def grouped_health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/resource", inject={"db": db})
async def injected_resource(db: str) -> dict[str, str]:
    return {"db": db}


# A resource declared in the type annotation needs no default and no cast:
# the parameter reads as ``str`` to the type checker.
DbDep = Annotated[str, db]


@app.get("/aliased")
async def aliased_resource(db: DbDep) -> dict[str, str]:
    return {"db": db}


app.include(group)

get_user_handler: Callable[[int], Awaitable[dict[str, int]]] = get_user
create_user_handler: Callable[[Request], Awaitable[Response]] = create_user
grouped_handler: Callable[[], Awaitable[dict[str, bool]]] = grouped_health
injected_handler: Callable[[str], Awaitable[dict[str, str]]] = injected_resource
aliased_handler: Callable[[str], Awaitable[dict[str, str]]] = aliased_resource
