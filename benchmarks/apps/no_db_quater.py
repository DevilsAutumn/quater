from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

import msgspec

from quater import (
    AuthConfig,
    AuthContext,
    BytesResponse,
    HTTPError,
    Quater,
    Query,
    Request,
)


class UserIn(msgspec.Struct):
    name: str
    age: int
    tags: list[str] = msgspec.field(default_factory=list)


async def authenticate(request: Request) -> AuthContext | None:
    if request.headers.get("authorization") != "Bearer benchmark-token":
        return None
    return AuthContext(subject="benchmark-user")


app = Quater(
    allowed_hosts=["127.0.0.1", "localhost"],
    max_body_size="4mb",
    auth=[AuthConfig(authenticate, surfaces=["api"])],
)


def json_payload(size: int) -> dict[str, object]:
    bounded = max(1, min(size, 1000))
    return {
        "count": bounded,
        "items": [{"id": index, "value": index * 2} for index in range(bounded)],
    }


def compute_payload(iterations: int) -> dict[str, object]:
    bounded = max(1, min(iterations, 500_000))
    started = perf_counter()
    total = 0
    for index in range(bounded):
        total = (total + index * index) % 1_000_000_007
    return {
        "iterations": bounded,
        "total": total,
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
    }


@app.get("/ping", public=True)
async def ping() -> dict[str, bool]:
    return {"ok": True}


@app.get("/health", public=True)
async def health() -> dict[str, object]:
    return {"ok": True, "service": "no-db-benchmark"}


@app.get("/json", public=True)
async def json_response(size: int = Query(default=10)) -> dict[str, object]:
    return json_payload(size)


@app.post("/echo", public=True)
async def echo(request: Request) -> dict[str, Any]:
    return {"body": await request.json()}


@app.post("/users")
async def create_user(user: UserIn, request: Request) -> dict[str, object]:
    if request.auth is None:
        raise HTTPError("Unauthorized", status_code=401)
    return {
        "subject": request.auth.subject,
        "name": user.name,
        "age": user.age,
        "tags": user.tags,
    }


@app.get("/bytes", public=True)
async def bytes_response(size: int = Query(default=1024)) -> BytesResponse:
    bounded = max(1, min(size, 1024 * 1024))
    return BytesResponse(b"x" * bounded)


@app.get("/compute", public=True)
async def compute(iterations: int = Query(default=10_000)) -> dict[str, object]:
    return compute_payload(iterations)


@app.get("/wait", public=True)
async def wait(delay_ms: int = Query(default=25)) -> dict[str, int]:
    bounded = max(0, min(delay_ms, 5000))
    await asyncio.sleep(bounded / 1000)
    return {"delay_ms": bounded}
