from __future__ import annotations

from typing import cast

import pytest

from quater import Quater
from quater.core import Handler
from quater.exceptions import RouteBindingError, RouteConflictError


def test_ambiguous_dynamic_route_shapes_are_rejected() -> None:
    app = Quater()

    @app.get("/users/{id}")
    async def by_id(id: str) -> dict[str, str]:
        return {"id": id}

    @app.get("/users/{name}")
    async def by_name(name: str) -> dict[str, str]:
        return {"name": name}

    with pytest.raises(RouteConflictError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "GET '/users/{name}' conflicts with GET '/users/{id}'" in message
    assert "same method and path shape are ambiguous" in message


def test_duplicate_method_and_path_are_rejected() -> None:
    app = Quater()

    @app.get("/health")
    async def first() -> dict[str, bool]:
        return {"first": True}

    @app.get("/health")
    async def second() -> dict[str, bool]:
        return {"second": True}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


@pytest.mark.parametrize(
    ("first_path", "second_path"),
    (
        ("/health", "/health/"),
        ("/api/health", "/api//health"),
        ("/", "///"),
    ),
)
def test_equivalent_paths_after_slash_normalization_are_rejected(
    first_path: str,
    second_path: str,
) -> None:
    app = Quater()

    @app.get(first_path)
    async def first() -> dict[str, bool]:
        return {"first": True}

    @app.get(second_path)
    async def second() -> dict[str, bool]:
        return {"second": True}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


def test_same_method_dynamic_routes_with_different_converters_are_rejected() -> None:
    app = Quater()

    @app.get("/users/{id:int}")
    async def by_id(id: int) -> dict[str, int]:
        return {"id": id}

    @app.get("/users/{id}")
    async def by_slug(id: str) -> dict[str, str]:
        return {"id": id}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


def test_dynamic_route_names_must_match_across_methods() -> None:
    app = Quater()

    @app.get("/users/{id:int}")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    @app.post("/users/{user_id:int}")
    async def update_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    with pytest.raises(RouteConflictError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "POST '/users/{user_id:int}' conflicts with GET '/users/{id:int}'" in message
    assert "Segment 2 uses {user_id:int}" in message
    assert "route '/users/{id:int}' uses {id:int}" in message


def test_dynamic_route_converters_must_match_for_same_shape() -> None:
    app = Quater()

    @app.get("/users/{id:int}")
    async def by_id(id: int) -> dict[str, int]:
        return {"id": id}

    @app.post("/users/{id}")
    async def by_slug(id: str) -> dict[str, str]:
        return {"id": id}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


def test_sync_handlers_are_rejected_at_compile_time() -> None:
    app = Quater()

    def sync_handler() -> dict[str, bool]:
        return {"ok": True}

    app.add_route("GET", "/sync", cast(Handler, sync_handler))

    with pytest.raises(RouteBindingError):
        app.compile_routes()


def test_invalid_route_paths_are_rejected_at_compile_time() -> None:
    app = Quater()

    @app.get("missing-leading-slash")
    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RouteBindingError):
        app.compile_routes()


@pytest.mark.parametrize(
    "path",
    (
        "/users/{id",
        "/users/id}",
        "/users/{}",
        "/users/{123}",
        "/users/{id:int:int}",
        "/users/{id:uuid}",
        "/users/{id:int}/{id:int}",
        "/users/{id}suffix",
    ),
)
def test_malformed_parameter_segments_are_rejected(path: str) -> None:
    app = Quater()

    @app.get(path)
    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RouteBindingError):
        app.compile_routes()
