"""Annotation helpers shared by generated documentation surfaces."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from inspect import Signature
from typing import cast, get_type_hints

from quater.core import RouteDefinition
from quater.exceptions import RouteBindingError


class _ReturnAnnotationProxy:
    __annotations__: dict[str, object]


def return_annotation(route: RouteDefinition) -> object:
    annotations = getattr(route.handler, "__annotations__", {})
    if not isinstance(annotations, dict):
        return Signature.empty

    annotation = annotations.get("return", Signature.empty)
    if annotation is Signature.empty:
        return Signature.empty

    proxy = _ReturnAnnotationProxy()
    proxy.__annotations__ = {"return": annotation}
    try:
        return get_type_hints(
            proxy,
            globalns=_callable_globalns(route.handler),
            include_extras=True,
        )["return"]
    except Exception as exc:
        raise _unresolved_response_annotation_error(route, annotation, exc) from exc


def _unresolved_response_annotation_error(
    route: RouteDefinition,
    annotation: object,
    exc: Exception,
) -> RouteBindingError:
    handler_name = getattr(
        route.handler,
        "__qualname__",
        getattr(route.handler, "__name__", "handler"),
    )
    return RouteBindingError(
        f"Response annotation for route {route.method} {route.path} on "
        f"handler {handler_name!r} has annotation {annotation!r} that could not "
        f"be resolved: {exc}. Define referenced response models at module scope "
        "before generating OpenAPI or MCP docs."
    )


def _callable_globalns(handler: object) -> dict[str, object]:
    target = inspect.unwrap(cast(Callable[..., object], handler))
    globalns = getattr(target, "__globals__", None)
    if isinstance(globalns, dict):
        return globalns
    return {}


__all__ = ["return_annotation"]
