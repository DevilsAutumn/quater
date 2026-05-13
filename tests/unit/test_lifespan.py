from __future__ import annotations

import pytest

from quater import Quater
from quater.exceptions import LifespanStateError, RouteConflictError


@pytest.mark.asyncio
async def test_lifespan_hooks_are_ordered_and_idempotent() -> None:
    app = Quater()
    events: list[str] = []

    @app.on_startup
    async def startup_one() -> None:
        events.append("startup_one")

    @app.on_startup
    async def startup_two() -> None:
        events.append("startup_two")

    @app.on_shutdown
    async def shutdown_one() -> None:
        events.append("shutdown_one")

    @app.on_shutdown
    async def shutdown_two() -> None:
        events.append("shutdown_two")

    await app.startup()
    await app.startup()
    await app.shutdown()
    await app.shutdown()

    assert events == [
        "startup_one",
        "startup_two",
        "shutdown_two",
        "shutdown_one",
    ]


@pytest.mark.asyncio
async def test_startup_failure_stops_later_hooks_and_never_runs_shutdown() -> None:
    class StartupFailed(Exception):
        pass

    app = Quater()
    events: list[str] = []

    @app.on_startup
    async def startup_one() -> None:
        events.append("startup_one")

    @app.on_startup
    async def startup_two() -> None:
        events.append("startup_two")
        raise StartupFailed

    @app.on_startup
    async def startup_three() -> None:
        events.append("startup_three")

    @app.on_shutdown
    async def shutdown_one() -> None:
        events.append("shutdown_one")

    with pytest.raises(StartupFailed):
        await app.startup()

    await app.shutdown()

    with pytest.raises(LifespanStateError):
        await app.startup()

    assert events == ["startup_one", "startup_two"]


@pytest.mark.asyncio
async def test_lifespan_hooks_cannot_be_registered_after_startup_begins() -> None:
    app = Quater()

    @app.on_startup
    async def startup() -> None:
        return None

    await app.startup()

    async def too_late() -> None:
        return None

    with pytest.raises(LifespanStateError):
        app.on_startup(too_late)

    with pytest.raises(LifespanStateError):
        app.on_shutdown(too_late)


@pytest.mark.asyncio
async def test_startup_compiles_routes_before_running_hooks() -> None:
    app = Quater()
    events: list[str] = []

    @app.on_startup
    async def startup() -> None:
        events.append("startup")

    @app.get("/orders/{order_id}")
    async def get_order(order_id: str) -> dict[str, str]:
        return {"order_id": order_id}

    @app.patch("/orders/{id}")
    async def update_order(id: str) -> dict[str, str]:
        return {"id": id}

    with pytest.raises(RouteConflictError):
        await app.startup()

    assert events == []
