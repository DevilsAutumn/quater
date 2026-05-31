"""Transport-neutral core contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from quater.dependencies import ResourceMap
from quater.exceptions import ConfigurationError
from quater.middleware import MiddlewareStack
from quater.typing import SURFACES, RequestSource

Handler: TypeAlias = Callable[..., Awaitable[object]]
PublicSurfaces: TypeAlias = "bool | Iterable[str]"

_SURFACE_SET: frozenset[RequestSource] = frozenset(SURFACES)


@dataclass(slots=True, frozen=True)
class RouteDefinition:
    """Route metadata registered on an application."""

    method: str
    path: str
    handler: Handler
    name: str
    description: str | None = None
    tool: bool = False
    cli: bool = False
    needs_approval: bool = False
    public: tuple[RequestSource, ...] = ()
    inject: ResourceMap = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    middleware: MiddlewareStack = field(default_factory=MiddlewareStack)


def exposed_surfaces(*, tool: bool, cli: bool) -> tuple[RequestSource, ...]:
    """The surfaces a route is reachable on, given its exposure flags.

    Every route is reachable over HTTP (``api``); ``tool=True`` adds ``mcp`` and
    ``cli=True`` adds ``cli``.
    """

    surfaces: list[RequestSource] = ["api"]
    if tool:
        surfaces.append("mcp")
    if cli:
        surfaces.append("cli")
    return tuple(surfaces)


def normalize_public(
    public: PublicSurfaces,
    *,
    tool: bool,
    cli: bool,
    route_name: str,
) -> tuple[RequestSource, ...]:
    """Normalize a route's ``public`` opt-out into the surfaces it opens.

    ``False`` is protected everywhere; ``True`` opens every surface the route is
    exposed on; a list opens exactly the named surfaces. A named surface must be
    one the route is actually exposed on, so a typo or a meaningless opt-out
    (``public=["mcp"]`` on a non-tool) fails loudly at definition time.
    """

    exposed = exposed_surfaces(tool=tool, cli=cli)
    if public is False:
        return ()
    if public is True:
        return exposed
    if isinstance(public, str):
        raise ConfigurationError(
            "public must be a bool or a list of surface names, not a string"
        )
    normalized: list[RequestSource] = []
    seen: set[str] = set()
    for surface in public:
        if surface not in _SURFACE_SET:
            raise ConfigurationError(
                f"Unknown public surface {surface!r}; expected one of "
                f"{', '.join(SURFACES)}"
            )
        if surface in seen:
            continue
        if surface not in exposed:
            raise ConfigurationError(
                f"Route {route_name!r} is marked public on {surface!r} but is not "
                f"exposed on that surface"
            )
        seen.add(surface)
        normalized.append(surface)
    return tuple(normalized)
