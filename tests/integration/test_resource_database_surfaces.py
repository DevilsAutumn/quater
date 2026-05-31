"""The real-DB resource lifecycle is identical across all three surfaces (#57).

Quater exposes one handler over three surfaces — HTTP ("api"), MCP tools, and
CLI actions — and the redesign's promise is that dependency injection and the
request lifecycle behave identically on each. The other ``test_resource_database``
modules live entirely on the HTTP surface; these drive the SAME handler, backed
by a real :class:`~sqlalchemy.ext.asyncio.AsyncSession`, over all three and
assert the same database outcome. That matters because MCP and CLI dispatch
through the action executor — a different teardown path than HTTP route
dispatch — so "the session opened, the write committed/rolled back, the session
closed" has to be proven there too, not just inferred from the HTTP case.

AuthConfig here is a plain token check (MCP and CLI require a surface authenticator);
the session is resolved for the handler, not the authenticator. AuthConfig using the
shared session is #54, not this issue.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quater import AuthConfig, AuthContext, Quater, Request, Resource, TestClient
from tests.support.database import (
    Database,
    Order,
    async_sessions,
    install_async_db,
    state_list,
)

TOKEN = "surface-token"


async def _allow(ctx: Request) -> AuthContext | None:
    if ctx.headers.get("authorization") == f"Bearer {TOKEN}":
        return AuthContext(subject="surface-user")
    return None


async def _session_provider(request: Request) -> AsyncIterator[AsyncSession]:
    session = async_sessions(request)()
    events = state_list(request, "db_events")
    if events is not None:
        events.append("open")
    try:
        yield session
    finally:
        await session.close()
        if events is not None:
            events.append("close")


_session = Resource(_session_provider, name="db")
Db = Annotated[AsyncSession, _session]

SURFACES = ["api", "mcp", "cli"]


def _app_with_db(database: Database, events: list[str]) -> Quater:
    app = Quater(auth=[AuthConfig(_allow, surfaces=["mcp", "cli"])])
    install_async_db(app, database)
    app.state.db_events = events
    return app


async def _invoke(
    client: TestClient,
    surface: str,
    *,
    method: str,
    path: str,
    action: str,
    arguments: dict[str, object],
) -> tuple[bool, object]:
    """Call the same handler over one surface; return (succeeded, payload).

    ``payload`` is the handler's decoded JSON result on success, so the three
    surfaces can be asserted against the same expected value.
    """

    if surface == "api":
        response = await client.request(method, path)
        ok = response.is_success
        return ok, (response.json() if ok else response.text)

    if surface == "mcp":
        response = await client.mcp.tools_call(action, arguments, token=TOKEN)
        result = response.json()["result"]
        ok = not result["isError"]
        text = result["content"][0]["text"]
        return ok, (json.loads(text) if ok else text)

    response = await client.cli.call(action, arguments, token=TOKEN)
    body = response.json()
    ok = response.status_code == 200 and "body" in body
    return ok, (body["body"] if ok else body)


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.asyncio
async def test_query_lifecycle_is_identical_across_surfaces(
    database: Database, surface: str
) -> None:
    events: list[str] = []
    app = _app_with_db(database, events)

    @app.get(
        "/orders/{user_id}", tool=True, cli=True, description="List a user's orders."
    )
    async def list_orders(user_id: str, db: Db) -> dict[str, list[str]]:
        result = await db.scalars(
            select(Order.item).where(Order.user_id == user_id).order_by(Order.id)
        )
        return {"items": list(result.all())}

    async with TestClient(app) as client:
        ok, payload = await _invoke(
            client,
            surface,
            method="GET",
            path="/orders/u_alice",
            action="list_orders",
            arguments={"user_id": "u_alice"},
        )

    assert ok
    assert payload == {"items": ["widget", "gadget"]}
    assert events == ["open", "close"]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.asyncio
async def test_committed_writes_persist_across_surfaces(
    database: Database, surface: str
) -> None:
    events: list[str] = []
    app = _app_with_db(database, events)

    @app.post("/orders/{user_id}", tool=True, cli=True, description="Create an order.")
    async def create_order(user_id: str, db: Db) -> dict[str, str]:
        db.add(Order(user_id=user_id, item="stapler", qty=7))
        await db.commit()
        return {"status": "created"}

    async with TestClient(app) as client:
        ok, payload = await _invoke(
            client,
            surface,
            method="POST",
            path="/orders/u_bob",
            action="create_order",
            arguments={"user_id": "u_bob"},
        )

    assert ok
    assert payload == {"status": "created"}
    assert database.order_items("u_bob") == ["gizmo", "stapler"]
    assert events == ["open", "close"]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.asyncio
async def test_uncommitted_writes_roll_back_across_surfaces(
    database: Database, surface: str
) -> None:
    events: list[str] = []
    app = _app_with_db(database, events)

    @app.post("/orders/{user_id}", tool=True, cli=True, description="Create an order.")
    async def create_order(user_id: str, db: Db) -> dict[str, str]:
        db.add(Order(user_id=user_id, item="stapler", qty=7))
        await db.flush()
        raise RuntimeError("boom")

    before = database.order_count()
    async with TestClient(app) as client:
        ok, _payload = await _invoke(
            client,
            surface,
            method="POST",
            path="/orders/u_bob",
            action="create_order",
            arguments={"user_id": "u_bob"},
        )

    assert not ok
    assert database.order_count() == before
    assert database.order_items("u_bob") == ["gizmo"]
    # Teardown still ran on the error path — on every surface.
    assert events == ["open", "close"]
