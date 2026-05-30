"""A real ORM-backed SQLite database harness for resource tests (issue #57).

The resource tests used to lean on a hand-written ``FakeSession`` and never
opened a real session or ran a real transaction. This harness gives them an
actual database driven through SQLAlchemy 2.0 — the same ORM the project's
benchmark app uses — so a Resource provider can hand a live ORM session to a
handler, the handler can query and write through it, and a test can assert what
genuinely landed on disk.

Both session styles the framework's resource system must support are covered:
an async :class:`~sqlalchemy.ext.asyncio.AsyncSession` over ``sqlite+aiosqlite``
and a synchronous :class:`~sqlalchemy.orm.Session` over ``sqlite+pysqlite``. A
:class:`Database` is a path, a long-lived read-back engine, and a few helpers;
build one with :func:`init_db` (the ``database`` fixture does that against a
fresh ``tmp_path`` file and disposes the read-back engine afterwards, so every
test is isolated).

An async engine binds to the event loop it is first used on, and pytest-asyncio
gives each test its own loop, so the app's engines are opened in a startup hook
— which runs on the request loop — via :func:`install_async_db` /
:func:`install_sync_db`, and disposed on shutdown. Providers read the session
factory back with :func:`async_sessions` / :func:`sync_sessions`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from sqlalchemy import Engine, ForeignKey, Integer, String, create_engine, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from quater import Quater, Request


class Base(DeclarativeBase):
    """Declarative base for the harness ORM models."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    token: Mapped[str] = mapped_column(String, nullable=False, unique=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    item: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)


# (id, name, token)
_USERS: tuple[tuple[str, str, str], ...] = (
    ("u_alice", "Alice", "token-alice"),
    ("u_bob", "Bob", "token-bob"),
)
# (user_id, item, qty) — seeded in this order, so order ids run 1..3.
_ORDERS: tuple[tuple[str, str, int], ...] = (
    ("u_alice", "widget", 2),
    ("u_alice", "gadget", 1),
    ("u_bob", "gizmo", 5),
)


def _sync_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def _async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


@dataclass(frozen=True, slots=True)
class Database:
    """A real SQLite database on disk, reachable through async and sync engines.

    The app under test opens its own engine via :func:`install_async_db` /
    :func:`install_sync_db`. Assertions read committed state back through the
    helper methods, which share ``engine`` — a separate, long-lived sync engine
    that never shares a connection (and so never shares transaction state) with
    the code under test. :func:`init_db` builds it; the ``database`` fixture
    disposes it.
    """

    path: Path
    engine: Engine = field(compare=False, repr=False)

    @property
    def sync_url(self) -> str:
        return _sync_url(self.path)

    @property
    def async_url(self) -> str:
        return _async_url(self.path)

    def sync_engine(self) -> Engine:
        return create_engine(self.sync_url)

    def async_engine(self) -> AsyncEngine:
        return create_async_engine(self.async_url)

    # -- read-back helpers: shared read-back engine, committed state only ------

    def order_items(self, user_id: str) -> list[str]:
        with Session(self.engine) as session:
            items = session.scalars(
                select(Order.item).where(Order.user_id == user_id).order_by(Order.id)
            ).all()
        return list(items)

    def order_count(self) -> int:
        with Session(self.engine) as session:
            count = session.scalar(select(func.count()).select_from(Order))
        return int(count or 0)


def init_db(path: Path) -> Database:
    """Create the schema and seed rows at ``path`` and return a handle.

    The returned :class:`Database` owns a read-back engine; dispose it (the
    ``database`` fixture does) once the test is done.
    """

    database = Database(path=path, engine=create_engine(_sync_url(path)))
    Base.metadata.create_all(database.engine)
    with Session(database.engine) as session:
        session.add_all(
            User(id=uid, name=name, token=token) for uid, name, token in _USERS
        )
        session.add_all(
            Order(user_id=uid, item=item, qty=qty) for uid, item, qty in _ORDERS
        )
        session.commit()
    return database


def install_async_db(app: Quater, database: Database) -> None:
    """Open an async engine on the app's request loop; dispose it on shutdown.

    Startup runs on the loop the requests use, so the engine binds to the right
    loop. Providers read the session factory back with :func:`async_sessions`.
    """

    @app.on_startup
    async def _open_async_db() -> None:
        engine = database.async_engine()
        app.state.async_engine = engine
        app.state.async_sessions = async_sessionmaker(engine, expire_on_commit=False)

    @app.on_shutdown
    async def _close_async_db() -> None:
        engine = app.state.async_engine
        if isinstance(engine, AsyncEngine):
            await engine.dispose()


def install_sync_db(app: Quater, database: Database) -> None:
    """Open a sync engine for the app; dispose it on shutdown.

    Providers read the session factory back with :func:`sync_sessions`.
    """

    @app.on_startup
    async def _open_sync_db() -> None:
        engine = database.sync_engine()
        app.state.sync_engine = engine
        app.state.sync_sessions = sessionmaker(engine, expire_on_commit=False)

    @app.on_shutdown
    async def _close_sync_db() -> None:
        engine = app.state.sync_engine
        if isinstance(engine, Engine):
            engine.dispose()


def async_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the async session factory the request's app was wired with."""

    factory = _app_state(request, "async_sessions")
    if not isinstance(factory, async_sessionmaker):
        raise RuntimeError("async database is not installed on this app")
    return cast("async_sessionmaker[AsyncSession]", factory)


def sync_sessions(request: Request) -> sessionmaker[Session]:
    """Return the sync session factory the request's app was wired with."""

    factory = _app_state(request, "sync_sessions")
    if not isinstance(factory, sessionmaker):
        raise RuntimeError("sync database is not installed on this app")
    return cast("sessionmaker[Session]", factory)


def state_list(request: Request, name: str) -> list[object] | None:
    """Return a named ``list`` stashed on ``app.state`` for test observability.

    Providers append open/close events (or opened sessions) to it and tests read
    it back. Returns ``None`` when the test installed no such list, so a provider
    stays silent instead of failing.
    """

    value = _app_state(request, name)
    return value if isinstance(value, list) else None


def _app_state(request: Request, name: str) -> object:
    app = request.app
    if app is None:
        raise RuntimeError("request is not bound to an application")
    return getattr(app.state, name, None)


__all__ = [
    "Base",
    "Database",
    "Order",
    "User",
    "async_sessions",
    "init_db",
    "install_async_db",
    "install_sync_db",
    "state_list",
    "sync_sessions",
]
