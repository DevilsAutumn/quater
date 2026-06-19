from __future__ import annotations

from typing import Annotated

import pytest

from quater import Path, Quater, Request
from quater.response import Response, TextResponse
from quater.typing import AuthContext


@pytest.mark.asyncio
async def test_path_params_are_converted_and_bound_by_name() -> None:
    app = Quater()

    @app.get("/users/{id:int}")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(Request(method="GET", path="/users/42"))

    assert response.status_code == 200
    assert response.body == b'{"id":42}'


@pytest.mark.asyncio
async def test_path_marker_alias_survives_postponed_annotations() -> None:
    app = Quater()

    @app.get("/orders/{id:int}")
    async def get_order(
        order_id: Annotated[int, Path(alias="id")],
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"order_id": order_id, "payload": payload}

    @app.get("/qualified-orders/{id:int}")
    async def get_qualified_order(
        order_id: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"order_id": order_id, "payload": payload}

    get_qualified_order.__annotations__["order_id"] = (
        "Annotated[int, 'route id', Path(alias='id')]"
    )

    @app.get("/literal-orders/{id:int}")
    async def get_literal_order(
        id: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"id": id, "payload": payload}

    get_literal_order.__annotations__["id"] = "Annotated[int, Path()]"

    response = await app.handle(Request(method="GET", path="/orders/42"))
    qualified_response = await app.handle(
        Request(method="GET", path="/qualified-orders/43")
    )
    literal_response = await app.handle(
        Request(method="GET", path="/literal-orders/44")
    )

    assert response.status_code == 200
    assert response.body == b'{"order_id":42,"payload":null}'
    assert qualified_response.status_code == 200
    assert qualified_response.body == b'{"order_id":43,"payload":null}'
    assert literal_response.status_code == 200
    assert literal_response.body == b'{"id":44,"payload":null}'


@pytest.mark.asyncio
async def test_request_injection_uses_same_request_object() -> None:
    app = Quater()
    auth = AuthContext(subject="user_1")

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        assert request.auth is auth
        return {"subject": request.auth.subject if request.auth else "none"}

    response = await app.handle(Request(method="GET", path="/whoami", auth=auth))

    assert response.status_code == 200
    assert response.body == b'{"subject":"user_1"}'


@pytest.mark.asyncio
async def test_request_named_parameter_tolerates_unresolved_annotation() -> None:
    app = Quater()

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        return {"path": request.path}

    whoami.__annotations__["request"] = "MissingRequest"
    response = await app.handle(Request(method="GET", path="/whoami"))

    assert response.status_code == 200
    assert response.body == b'{"path":"/whoami"}'


@pytest.mark.asyncio
async def test_handler_response_objects_pass_through_normalization() -> None:
    app = Quater()

    @app.get("/ready")
    async def ready() -> Response:
        return TextResponse("ready", status_code=202)

    response = await app.handle(Request(method="GET", path="/ready"))

    assert response.status_code == 202
    assert response.body == b"ready"


@pytest.mark.asyncio
async def test_unsupported_handler_return_value_is_not_silently_serialized() -> None:
    class Unsupported:
        pass

    app = Quater()

    @app.get("/bad")
    async def bad() -> Unsupported:
        return Unsupported()

    response = await app.handle(Request(method="GET", path="/bad"))

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"
