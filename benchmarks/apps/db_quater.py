from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, Text, func, insert, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from quater import AuthConfig, AuthContext, HTTPError, Quater, Request, Resource

DATABASE_URL = os.getenv(
    "BENCHMARK_DATABASE_URL",
    "postgresql+asyncpg://quater:quater@127.0.0.1:5433/quater_bench",
)
POOL_SIZE = int(os.getenv("BENCHMARK_DB_POOL_SIZE", "10"))
TOKEN = os.getenv("BENCHMARK_TOKEN", "benchmark-token")


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    sku: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(Text, ForeignKey("products.sku"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)


async def prepare_database(session: AsyncSession) -> None:
    product_count = await session.scalar(select(func.count()).select_from(Product))
    if product_count == 0:
        await session.execute(
            insert(Product),
            [
                {
                    "sku": f"SKU-{index:04d}",
                    "name": f"Benchmark product {index}",
                    "price_cents": 1000 + index,
                    "stock": 10 + index % 90,
                }
                for index in range(1, 501)
            ],
        )

    order_count = await session.scalar(select(func.count()).select_from(Order))
    if order_count == 0:
        await session.execute(
            insert(Order),
            [
                {
                    "sku": f"SKU-{(index % 500) + 1:04d}",
                    "quantity": (index % 4) + 1,
                    "total_cents": (1000 + index) * ((index % 4) + 1),
                    "status": "paid" if index % 3 else "shipped",
                }
                for index in range(1, 2001)
            ],
        )

    await session.commit()


async def authenticate(request: Request) -> AuthContext | None:
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
        return None
    return AuthContext(subject="benchmark-user")


app = Quater(
    allowed_hosts=["127.0.0.1", "localhost"],
    max_body_size="2mb",
    auth=[AuthConfig(authenticate, surfaces=["api"])],
)


@app.on_startup
async def startup() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=POOL_SIZE)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True)
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await prepare_database(session)
    app.state.engine = engine
    app.state.session_factory = session_factory


@app.on_shutdown
async def shutdown() -> None:
    await app.state.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


db_session = Resource(get_session, name="db_session")


@app.get("/ping", public=True)
async def ping() -> dict[str, bool]:
    return {"ok": True}


@app.get("/health", public=True, inject={"session": db_session})
async def health(session: AsyncSession) -> dict[str, bool]:
    result = await session.execute(text("SELECT 1"))
    return {"ok": result.scalar() == 1}


@app.get("/products", inject={"session": db_session})
async def products(session: AsyncSession, limit: int = 50) -> dict[str, object]:
    bounded = max(1, min(limit, 100))
    result = await session.execute(
        select(Product).where(Product.stock > 0).order_by(Product.sku).limit(bounded)
    )
    return {
        "items": [
            {
                "sku": p.sku,
                "name": p.name,
                "price_cents": p.price_cents,
                "stock": p.stock,
            }
            for p in result.scalars()
        ]
    }


@app.get("/products/{sku}", inject={"session": db_session})
async def product(sku: str, session: AsyncSession) -> dict[str, Any]:
    p = await session.get(Product, sku)
    if p is None:
        raise HTTPError("Product not found", status_code=404)
    return {
        "sku": p.sku,
        "name": p.name,
        "price_cents": p.price_cents,
        "stock": p.stock,
    }


@app.get("/orders", inject={"session": db_session})
async def orders(session: AsyncSession, limit: int = 25) -> dict[str, object]:
    bounded = max(1, min(limit, 100))
    result = await session.execute(
        select(Order).order_by(Order.id.desc()).limit(bounded)
    )
    return {
        "items": [
            {
                "id": o.id,
                "sku": o.sku,
                "quantity": o.quantity,
                "total_cents": o.total_cents,
                "status": o.status,
            }
            for o in result.scalars()
        ]
    }


@app.get("/reports/summary", inject={"session": db_session})
async def summary(session: AsyncSession) -> dict[str, Any]:
    products_count = select(func.count()).select_from(Product).scalar_subquery()
    orders_count = select(func.count()).select_from(Order).scalar_subquery()
    revenue_cents = select(
        func.coalesce(func.sum(Order.total_cents), 0)
    ).scalar_subquery()
    stock_total = select(func.coalesce(func.sum(Product.stock), 0)).scalar_subquery()
    row = (
        await session.execute(
            select(
                products_count.label("products"),
                orders_count.label("orders"),
                revenue_cents.label("revenue_cents"),
                stock_total.label("stock"),
            )
        )
    ).one()
    return dict(row._mapping)
