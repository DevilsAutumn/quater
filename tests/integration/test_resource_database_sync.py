"""Resource lifecycle against a real sync ORM session (issue #57).

The companion to ``test_resource_database_async``: the resource system must work
just as well when a provider hands back a synchronous resource. These tests use
a SQLAlchemy :class:`~sqlalchemy.orm.Session` (over ``sqlite+pysqlite``) through
both sync provider shapes the framework supports — a plain generator and a
``@contextmanager`` — and assert the same real behaviours: live queries,
committed writes persisting, and an uncommitted unit of work rolling back when
the session closes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quater import Quater, Request, Resource, TestClient
from tests.support.database import (
    Database,
    Order,
    install_sync_db,
    state_list,
    sync_sessions,
)


def _sync_session_provider(request: Request) -> Iterator[Session]:
    session = sync_sessions(request)()
    events = state_list(request, "db_events")
    if events is not None:
        events.append("open")
    try:
        yield session
    finally:
        session.close()
        if events is not None:
            events.append("close")


_sync_session = Resource(_sync_session_provider, name="db")
Db = Annotated[Session, _sync_session]


@contextmanager
def _sync_context_session_provider(request: Request) -> Iterator[Session]:
    session = sync_sessions(request)()
    events = state_list(request, "db_events")
    if events is not None:
        events.append("open")
    try:
        yield session
    finally:
        session.close()
        if events is not None:
            events.append("close")


_sync_context_session = Resource(_sync_context_session_provider, name="db")
ContextDb = Annotated[Session, _sync_context_session]


@pytest.mark.asyncio
async def test_session_resource_serves_queries_and_closes(database: Database) -> None:
    events: list[str] = []

    app = Quater()
    install_sync_db(app, database)
    app.state.db_events = events

    @app.get("/orders")
    async def list_orders(db: Db) -> dict[str, list[str]]:
        items = db.scalars(
            select(Order.item).where(Order.user_id == "u_alice").order_by(Order.id)
        ).all()
        return {"items": list(items)}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.json() == {"items": ["widget", "gadget"]}
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_committed_writes_persist(database: Database) -> None:
    app = Quater()
    install_sync_db(app, database)

    @app.post("/orders")
    async def create_order(db: Db) -> dict[str, str]:
        db.add(Order(user_id="u_bob", item="stapler", qty=7))
        db.commit()
        return {"status": "created"}

    async with TestClient(app) as client:
        response = await client.post("/orders")

    assert response.json() == {"status": "created"}
    assert database.order_items("u_bob") == ["gizmo", "stapler"]


@pytest.mark.asyncio
async def test_uncommitted_writes_roll_back_when_handler_raises(
    database: Database,
) -> None:
    app = Quater()
    install_sync_db(app, database)

    @app.post("/orders")
    async def create_order(db: Db) -> dict[str, str]:
        db.add(Order(user_id="u_bob", item="stapler", qty=7))
        # Flush sends the INSERT inside the transaction, then we raise before
        # committing: closing the session in teardown rolls it back.
        db.flush()
        raise RuntimeError("boom")

    before = database.order_count()
    async with TestClient(app) as client:
        response = await client.post("/orders")

    assert response.status_code == 500
    assert database.order_count() == before
    assert database.order_items("u_bob") == ["gizmo"]


@pytest.mark.asyncio
async def test_context_manager_provider_cleans_up(database: Database) -> None:
    events: list[str] = []

    app = Quater()
    install_sync_db(app, database)
    app.state.db_events = events

    @app.get("/orders")
    async def list_orders(db: ContextDb) -> dict[str, int]:
        count = db.scalar(select(func.count()).select_from(Order))
        return {"orders": int(count or 0)}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.json() == {"orders": 3}
    assert events == ["open", "close"]
