from __future__ import annotations

from collections.abc import Callable
from typing import cast

import msgspec
import pytest

from quater import Quater, Request


class CreateUser(msgspec.Struct):
    name: str
    age: int


@pytest.mark.asyncio
async def test_query_params_are_converted_and_defaults_are_applied() -> None:
    app = Quater()

    @app.get("/search")
    async def search(q: str, page: int = 1, active: bool = False) -> dict[str, object]:
        return {"q": q, "page": page, "active": active}

    response = await app.handle(
        Request(method="GET", path="/search", query_string="q=ada&active=true")
    )

    assert response.status_code == 200
    assert response.body == b'{"q":"ada","page":1,"active":true}'


@pytest.mark.asyncio
async def test_missing_required_query_param_returns_validation_error() -> None:
    app = Quater()
    calls = 0

    @app.get("/search")
    async def search(q: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"q": q}

    response = await app.handle(Request(method="GET", path="/search"))

    assert response.status_code == 400
    assert response.body == b"Missing required query parameter: q"
    assert dict(response.headers)["x-content-type-options"] == "nosniff"
    assert calls == 0


@pytest.mark.asyncio
async def test_json_body_is_bound_to_typed_struct() -> None:
    app = Quater()

    @app.post("/users")
    async def create_user(user: CreateUser) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    response = await app.handle(
        Request(method="POST", path="/users", body=b'{"name":"Ada","age":37}')
    )

    assert response.status_code == 200
    assert response.body == b'{"name":"Ada","age":37}'


@pytest.mark.asyncio
async def test_missing_required_json_body_returns_validation_error() -> None:
    app = Quater()
    calls = 0

    @app.post("/users")
    async def create_user(user: CreateUser) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"name": user.name, "age": user.age}

    response = await app.handle(Request(method="POST", path="/users"))

    assert response.status_code == 400
    assert response.body == b"Missing required body parameter: user"
    assert calls == 0


@pytest.mark.asyncio
async def test_missing_optional_json_body_binds_none() -> None:
    app = Quater()

    @app.post("/users")
    async def create_user(user: CreateUser | None = None) -> dict[str, object]:
        return {
            "has_user": user is not None,
        }

    response = await app.handle(Request(method="POST", path="/users"))

    assert response.status_code == 200
    assert response.body == b'{"has_user":false}'


@pytest.mark.asyncio
async def test_typed_json_body_decodes_directly_into_handler_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Quater()
    original_decode = cast(Callable[..., object], msgspec.json.decode)
    decoded_types: list[object] = []

    def decode_json(*args: object, **kwargs: object) -> object:
        decoded_types.append(kwargs.get("type"))
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(msgspec.json, "decode", decode_json)

    @app.post("/users")
    async def create_user(user: CreateUser) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    response = await app.handle(
        Request(method="POST", path="/users", body=b'{"name":"Ada","age":37}')
    )

    assert response.status_code == 200
    assert decoded_types == [CreateUser]


@pytest.mark.asyncio
async def test_invalid_json_body_rejects_before_handler_execution() -> None:
    app = Quater()
    calls = 0

    @app.post("/users")
    async def create_user(user: CreateUser) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"name": user.name, "age": user.age}

    response = await app.handle(
        Request(method="POST", path="/users", body=b'{"name":"Ada"}')
    )

    assert response.status_code == 400
    assert response.body == b"Invalid JSON body for parameter: user"
    assert calls == 0


@pytest.mark.asyncio
async def test_malformed_typed_json_body_keeps_parse_error_message() -> None:
    app = Quater()
    calls = 0

    @app.post("/users")
    async def create_user(user: CreateUser) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"name": user.name, "age": user.age}

    response = await app.handle(
        Request(method="POST", path="/users", body=b'{"name":"Ada"')
    )

    assert response.status_code == 400
    assert response.body == b"Malformed JSON body"
    assert calls == 0
