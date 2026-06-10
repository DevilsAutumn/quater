from __future__ import annotations

import json
from typing import Annotated

import msgspec
import pytest

from quater import AuthConfig, Body, Cookie, Header, Path, Quater, Query, Request
from quater.exceptions import RouteBindingError
from quater.typing import AuthContext


class CreateOrder(msgspec.Struct):
    sku: str
    quantity: int


async def allow_auth(_ctx: Request) -> AuthContext | None:
    return AuthContext(subject="test")


ORDER_BODY = Body(description="Order payload.")
BAD_BODY_ALIAS = Body(alias="bad-name")
COLLIDING_BODY_ALIAS = Body(alias="order_id")
TAGS_QUERY = Query()


@pytest.mark.asyncio
async def test_markers_bind_path_query_header_cookie_and_body_aliases() -> None:
    app = Quater()

    @app.post("/orders/{id}")
    async def create_order(
        order_id: str = Path(alias="id", description="Route order id."),
        include_events: bool = Query(
            default=False,
            alias="include-events",
            description="Include event history.",
        ),
        request_id: str = Header(
            alias="X-Request-ID",
            description="Caller request id.",
        ),
        session_id: str = Cookie(alias="session"),
        order: CreateOrder = ORDER_BODY,
    ) -> dict[str, object]:
        return {
            "order_id": order_id,
            "include_events": include_events,
            "request_id": request_id,
            "session_id": session_id,
            "sku": order.sku,
            "quantity": order.quantity,
        }

    response = await app.handle(
        Request(
            method="POST",
            path="/orders/ord_1001",
            query_string="include-events=true",
            headers={
                "X-Request-ID": "req_123",
                "Cookie": "session=sess_123",
            },
            body=b'{"sku":"sku_coffee","quantity":2}',
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "order_id": "ord_1001",
        "include_events": True,
        "request_id": "req_123",
        "session_id": "sess_123",
        "sku": "sku_coffee",
        "quantity": 2,
    }


@pytest.mark.asyncio
async def test_annotated_markers_use_signature_defaults() -> None:
    app = Quater()

    @app.get("/search")
    async def search(
        q: Annotated[str, Query(description="Search text")],
        page: Annotated[int, Query(alias="p")] = 1,
        user_agent: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        return {"q": q, "page": page, "user_agent": user_agent}

    response = await app.handle(
        Request(
            method="GET",
            path="/search",
            query_string="q=coffee",
            headers={"User-Agent": "quater-test"},
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "q": "coffee",
        "page": 1,
        "user_agent": "quater-test",
    }


@pytest.mark.asyncio
async def test_missing_required_header_and_cookie_return_clear_errors() -> None:
    app = Quater()

    @app.get("/profile")
    async def profile(
        request_id: str = Header(alias="X-Request-ID"),
        session_id: str = Cookie(alias="session"),
    ) -> dict[str, str]:
        return {"request_id": request_id, "session_id": session_id}

    missing_header = await app.handle(Request(method="GET", path="/profile"))
    missing_cookie = await app.handle(
        Request(
            method="GET",
            path="/profile",
            headers={"X-Request-ID": "req_123"},
        )
    )

    assert missing_header.status_code == 400
    assert missing_header.body == b"Missing required header: X-Request-ID"
    assert missing_cookie.status_code == 400
    assert missing_cookie.body == b"Missing required cookie: session"


@pytest.mark.asyncio
async def test_leading_reserved_cookie_name_does_not_hide_session() -> None:
    app = Quater()

    @app.get("/cookie")
    async def read_cookie(session: str = Cookie()) -> dict[str, str]:
        return {"session": session}

    response = await app.handle(
        Request(
            method="GET",
            path="/cookie",
            headers={"Cookie": "path=/admin; session=abc"},
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"session": "abc"}


@pytest.mark.asyncio
async def test_header_marker_converts_underscores_by_default() -> None:
    app = Quater()

    @app.get("/agent")
    async def agent(user_agent: str = Header()) -> dict[str, str]:
        return {"user_agent": user_agent}

    response = await app.handle(
        Request(
            method="GET",
            path="/agent",
            headers={"User-Agent": "quater-test"},
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"user_agent": "quater-test"}


def test_path_marker_alias_must_match_route_parameter() -> None:
    app = Quater()

    @app.get("/orders/{id}")
    async def get_order(order_id: str = Path(alias="order_id")) -> dict[str, str]:
        return {"order_id": order_id}

    with pytest.raises(RouteBindingError, match="does not match route path"):
        app.compile_routes()


def test_path_parameter_cannot_use_query_marker() -> None:
    app = Quater()

    @app.get("/orders/{order_id}")
    async def get_order(order_id: str = Query()) -> dict[str, str]:
        return {"order_id": order_id}

    with pytest.raises(RouteBindingError, match="cannot use query binding"):
        app.compile_routes()


def test_parameter_cannot_define_marker_default_twice() -> None:
    app = Quater()

    @app.get("/search")
    async def search(
        page: Annotated[int, Query(default=1)] = 2,
    ) -> dict[str, int]:
        return {"page": page}

    with pytest.raises(RouteBindingError, match="cannot define a default twice"):
        app.compile_routes()


def test_header_marker_rejects_invalid_header_names() -> None:
    app = Quater()

    @app.get("/bad")
    async def bad(header: str = Header(alias="Bad Header")) -> dict[str, str]:
        return {"header": header}

    with pytest.raises(RouteBindingError, match="Invalid header parameter name"):
        app.compile_routes()


def test_body_alias_must_be_action_argument_identifier() -> None:
    app = Quater()

    @app.post("/bad")
    async def bad(payload: CreateOrder = BAD_BODY_ALIAS) -> dict[str, str]:
        return {"sku": payload.sku}

    with pytest.raises(RouteBindingError, match="must use an identifier alias"):
        app.compile_routes()


def test_duplicate_http_parameter_names_are_rejected() -> None:
    app = Quater()

    @app.get("/orders/{id}")
    async def get_order(
        id: str,
        order_id: str = Path(alias="id"),
    ) -> dict[str, str]:
        return {"id": id, "order_id": order_id}

    with pytest.raises(RouteBindingError, match="Duplicate request parameter name"):
        app.compile_routes()


def test_duplicate_action_argument_names_are_rejected() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.post("/orders/{id}", cli=True, description="Create order.")
    async def create_order(
        order_id: str = Path(alias="id"),
        payload: CreateOrder = COLLIDING_BODY_ALIAS,
    ) -> dict[str, str]:
        return {"order_id": order_id, "sku": payload.sku}

    with pytest.raises(RouteBindingError, match="Duplicate action argument name"):
        app.compile_routes()


def test_marker_bound_query_parameters_must_use_scalar_annotations() -> None:
    app = Quater()

    @app.get("/search")
    async def search(tags: list[str] = TAGS_QUERY) -> dict[str, object]:
        return {"tags": tags}

    with pytest.raises(RouteBindingError, match="Query parameter"):
        app.compile_routes()
