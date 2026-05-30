"""Resource lifecycle against a real async ORM session (issue #57).

These tests inject a live SQLAlchemy ``AsyncSession`` (over ``sqlite+aiosqlite``)
instead of a fake, so the resource system is exercised end to end: a provider
opens a real session, a handler queries and writes through the ORM, and the
framework closes the session on teardown. Because that lets us inspect what
actually landed on disk, they assert the two things a fake never could —
committed writes persist, and an uncommitted unit of work rolls back when the
session closes.

The framework tears the resource scope down with a clean ``aclose`` on both the
success and the error path (``params.py``: it never throws the handler's
exception into the provider). So the correct unit-of-work pattern — the same one
the SQLAlchemy benchmark app uses — is for the handler to commit explicitly; a
handler that raises never reaches the commit, and closing the session discards
the open transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quater import Quater, Request, Resource, StreamResponse, TestClient
from tests.support.database import (
    Database,
    Order,
    User,
    async_sessions,
    install_async_db,
    state_list,
)


async def _async_session_provider(request: Request) -> AsyncIterator[AsyncSession]:
    session = async_sessions(request)()
    opened = state_list(request, "opened_sessions")
    events = state_list(request, "db_events")
    if opened is not None:
        opened.append(session)
    if events is not None:
        events.append("open")
    try:
        yield session
    finally:
        await session.close()
        if events is not None:
            events.append("close")


_async_session = Resource(_async_session_provider, name="db")
Db = Annotated[AsyncSession, _async_session]


@pytest.mark.asyncio
async def test_session_resource_serves_queries_and_closes(database: Database) -> None:
    events: list[str] = []

    app = Quater()
    install_async_db(app, database)
    app.state.db_events = events

    @app.get("/orders")
    async def list_orders(db: Db) -> dict[str, list[str]]:
        result = await db.scalars(
            select(Order.item).where(Order.user_id == "u_alice").order_by(Order.id)
        )
        return {"items": list(result.all())}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.json() == {"items": ["widget", "gadget"]}
    # The provider opened a real session and the framework drove its teardown.
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_committed_writes_persist(database: Database) -> None:
    app = Quater()
    install_async_db(app, database)

    @app.post("/orders")
    async def create_order(db: Db) -> dict[str, str]:
        db.add(Order(user_id="u_bob", item="stapler", qty=7))
        await db.commit()
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
    install_async_db(app, database)

    @app.post("/orders")
    async def create_order(db: Db) -> dict[str, str]:
        db.add(Order(user_id="u_bob", item="stapler", qty=7))
        # Flush sends the INSERT inside the transaction, then we raise before
        # committing: teardown closes the session and the open transaction is
        # rolled back, so the row must never reach disk.
        await db.flush()
        raise RuntimeError("boom")

    before = database.order_count()
    async with TestClient(app) as client:
        response = await client.post("/orders")

    assert response.status_code == 500
    assert database.order_count() == before
    assert database.order_items("u_bob") == ["gizmo"]


# --- Resource-on-resource over one shared session (issues #52/#53) ------------
# The Annotated[T, resource] aliases live at module scope so get_type_hints can
# resolve them. Per-request state is wired through app.state inside each test.

_shared_opened: list[object] = []
_shared_seen: dict[str, AsyncSession] = {}


async def _current_user_provider(db: Db) -> dict[str, str]:
    _shared_seen["dependency"] = db
    user = (await db.scalars(select(User).where(User.token == "token-alice"))).one()
    # Write on the shared session without committing; the handler's commit must
    # persist this row too, which only holds if the dependency and the handler
    # share one session and therefore one transaction.
    db.add(Order(user_id=user.id, item="audit", qty=0))
    await db.flush()
    return {"id": user.id, "name": user.name}


_current_user = Resource(_current_user_provider, name="current_user")
CurrentUser = Annotated[dict[str, str], _current_user]


@pytest.mark.asyncio
async def test_resource_dependency_shares_one_session_and_transaction(
    database: Database,
) -> None:
    _shared_opened.clear()
    _shared_seen.clear()

    app = Quater()
    install_async_db(app, database)
    app.state.opened_sessions = _shared_opened

    @app.post("/orders")
    async def create_order(db: Db, user: CurrentUser) -> dict[str, str]:
        _shared_seen["handler"] = db
        db.add(Order(user_id=user["id"], item="widget", qty=3))
        await db.commit()
        return {"user": user["id"]}

    async with TestClient(app) as client:
        response = await client.post("/orders")

    assert response.json() == {"user": "u_alice"}
    # One session for the whole request, shared by the dependency and the
    # handler — the same object, opened exactly once.
    assert len(_shared_opened) == 1
    assert _shared_seen["dependency"] is _shared_seen["handler"]
    # Both inserts — the dependency's "audit" and the handler's "widget" — were
    # committed together by the handler's single commit.
    assert database.order_items("u_alice") == ["widget", "gadget", "audit", "widget"]


@pytest.mark.asyncio
async def test_streaming_keeps_session_open_until_consumed(database: Database) -> None:
    events: list[str] = []

    app = Quater()
    install_async_db(app, database)
    app.state.db_events = events

    @app.get("/orders/stream")
    async def stream_orders(db: Db) -> StreamResponse:
        async def body() -> AsyncIterator[bytes]:
            result = await db.scalars(
                select(Order.item).where(Order.user_id == "u_alice").order_by(Order.id)
            )
            for item in result.all():
                events.append(f"chunk:{item}")
                yield f"{item}\n".encode()

        return StreamResponse(body())

    async with TestClient(app) as client:
        response = await client.get("/orders/stream")

    assert response.body == b"widget\ngadget\n"
    # The session stays live through streaming and closes only after the body is
    # fully consumed — never before the first chunk is produced.
    assert events == ["open", "chunk:widget", "chunk:gadget", "close"]
