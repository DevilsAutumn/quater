from __future__ import annotations

from inspect import Signature
from typing import cast

from quater.core import Handler, RouteDefinition
from quater.docs.annotations import return_annotation


def _route(handler: object) -> RouteDefinition:
    return RouteDefinition(
        method="GET",
        path="/items",
        handler=cast(Handler, handler),
        name="items",
    )


class _HandlerWithoutReturnAnnotation:
    __annotations__: dict[str, object] = {}

    async def __call__(self) -> object:
        return {"ok": True}


class _HandlerWithMalformedAnnotations:
    async def __call__(self) -> object:
        return {"ok": True}


class _HandlerWithoutGlobals:
    __annotations__ = {"return": int}

    async def __call__(self) -> object:
        return 1


def test_return_annotation_is_empty_when_handler_has_no_return_annotation() -> None:
    assert (
        return_annotation(_route(_HandlerWithoutReturnAnnotation())) is Signature.empty
    )


def test_return_annotation_ignores_malformed_handler_annotations() -> None:
    handler = _HandlerWithMalformedAnnotations()
    handler.__dict__["__annotations__"] = "not-a-dict"

    assert return_annotation(_route(handler)) is Signature.empty


def test_return_annotation_resolves_when_callable_has_no_globals() -> None:
    assert return_annotation(_route(_HandlerWithoutGlobals())) is int
