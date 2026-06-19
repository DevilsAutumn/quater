from __future__ import annotations

import typing
from typing import Annotated, Any, Literal, cast

import pytest

from quater import Path, Quater
from quater.core import Handler
from quater.exceptions import RouteBindingError, RouteConflictError


class UnsupportedPathValue:
    pass


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


def test_path_int_annotation_requires_int_converter() -> None:
    app = Quater()

    @app.get("/items/{item_id}")
    async def get_item(item_id: int) -> dict[str, object]:
        return {"item_id": item_id}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'item_id'" in message
    assert "annotated as int" in message
    assert "{item_id}" in message
    assert "{item_id:int}" in message


def test_int_path_converter_requires_int_annotation() -> None:
    app = Quater()

    @app.get("/items/{item_id:int}")
    async def get_item(item_id: str) -> dict[str, object]:
        return {"item_id": item_id}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'item_id'" in message
    assert "annotated as str" in message
    assert "{item_id:int}" in message
    assert "{item_id}" in message


def test_path_marker_alias_annotation_must_match_converter() -> None:
    app = Quater()

    @app.get("/orders/{id:int}")
    async def get_order(order_id: str = Path(alias="id")) -> dict[str, object]:
        return {"order_id": order_id}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'order_id'" in message
    assert "route parameter 'id'" in message
    assert "annotated as str" in message
    assert "{id:int}" in message


def test_matching_path_converter_annotations_are_allowed() -> None:
    app = Quater()

    @app.get("/items/{item_id:int}")
    async def get_item(item_id: int) -> dict[str, object]:
        return {"item_id": item_id}

    @app.get("/maybe-items/{item_id:int}")
    async def get_maybe_item(item_id: int | None) -> dict[str, object]:
        return {"item_id": item_id}

    @app.get("/orders/{id:int}")
    async def get_order(
        order_id: Annotated[int, Path(alias="id")],
    ) -> dict[str, object]:
        return {"order_id": order_id}

    @app.get("/slugs/{slug}")
    async def get_slug(slug: str) -> dict[str, object]:
        return {"slug": slug}

    @app.get("/generic/{value:int}")
    async def get_generic(value: Any) -> dict[str, object]:
        return {"value": value}

    @app.get("/untyped/{value:int}")
    async def get_untyped(value) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {"value": value}

    app.compile_routes()


@pytest.mark.parametrize(
    ("path", "annotation"),
    (
        ("/values/{value}", bool),
        ("/values/{value}", float),
        ("/values/{value}", list[str]),
        ("/values/{value}", Literal["active"]),
        ("/values/{value:int}", bool),
        ("/values/{value:int}", float),
        ("/values/{value:int}", Literal[1]),
    ),
)
def test_path_parameters_reject_unsupported_concrete_annotations(
    path: str,
    annotation: object,
) -> None:
    app = Quater()

    async def handler(value: object) -> dict[str, object]:
        return {"value": value}

    handler.__annotations__["value"] = annotation
    app.add_route("GET", path, handler)

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'value'" in message
    assert (
        "Path parameter annotations must match a supported route converter" in message
    )


def test_path_annotation_validation_handles_postponed_annotations() -> None:
    app = Quater()

    @app.post("/items/{item_id:int}")
    async def update_item(
        item_id: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    @app.post("/optional-items/{item_id:int}")
    async def update_optional_item(
        item_id: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    update_optional_item.__annotations__["item_id"] = "int | None"

    @app.post("/maybe-items/{item_id:int}")
    async def update_maybe_item(
        item_id: int | None,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    app.compile_routes()


def test_path_annotation_mismatch_rejects_postponed_annotation() -> None:
    app = Quater()

    @app.post("/items/{item_id}")
    async def update_item(
        item_id: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'item_id'" in message
    assert "annotated as int" in message
    assert "{item_id:int}" in message


def test_path_annotation_rejects_unsupported_concrete_path_type() -> None:
    app = Quater()

    @app.get("/values/{value}")
    async def get_value(value: UnsupportedPathValue) -> dict[str, object]:
        return {"value": value}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'value'" in message
    assert "UnsupportedPathValue" in message
    assert (
        "Path parameter annotations must match a supported route converter" in message
    )


def test_path_union_annotation_rejects_postponed_annotation() -> None:
    app = Quater()

    @app.get("/values/{value}")
    async def get_value(
        value: int | str,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"value": value, "payload": payload}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'value'" in message
    assert "int | str" in message
    assert (
        "Path parameter annotations must match a supported route converter" in message
    )


def test_path_typing_union_annotation_label_is_stable() -> None:
    app = Quater()

    @app.get("/values/{value}")
    async def get_value(value: object) -> dict[str, object]:
        return {"value": value}

    get_value.__annotations__["value"] = typing.Union[int, str]  # noqa: UP007

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'value'" in message
    assert "int | str" in message
    assert "Union" not in message


def test_path_opaque_annotation_label_uses_repr() -> None:
    class OpaqueAnnotation:
        def __repr__(self) -> str:
            return "OpaqueAnnotation()"

    app = Quater()

    @app.get("/values/{value}")
    async def get_value(value: object) -> dict[str, object]:
        return {"value": value}

    get_value.__annotations__["value"] = OpaqueAnnotation()

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "Path parameter 'value'" in message
    assert "OpaqueAnnotation()" in message


def test_path_annotation_duplicate_markers_reject() -> None:
    app = Quater()

    @app.get("/values/{value:int}")
    async def get_value(
        value: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"value": value, "payload": payload}

    get_value.__annotations__["value"] = "Annotated[int, Path(), Path()]"

    with pytest.raises(RouteBindingError, match="Only one parameter marker"):
        app.compile_routes()


def test_incomplete_annotated_path_string_rejects() -> None:
    app = Quater()

    @app.get("/values/{value:int}")
    async def get_value(
        value: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"value": value, "payload": payload}

    get_value.__annotations__["value"] = "Annotated[int]"

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "value" in message
    assert "could not be resolved" in message
    assert "Annotated[int]" in message


def test_malformed_path_string_rejects() -> None:
    app = Quater()

    @app.get("/values/{value:int}")
    async def get_value(
        value: int,
        payload: object | None = None,
    ) -> dict[str, object]:
        return {"value": value, "payload": payload}

    get_value.__annotations__["value"] = "Annotated[int"

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "value" in message
    assert "could not be resolved" in message
    assert "Annotated[int" in message


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
