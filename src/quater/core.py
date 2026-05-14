"""Transport-neutral core contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from quater.dependencies import ResourceMap
from quater.middleware import MiddlewareStack
from quater.typing import Authenticate

Handler: TypeAlias = Callable[..., Awaitable[object]]


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
    auth: Authenticate | None = None
    inject: ResourceMap = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    middleware: MiddlewareStack = field(default_factory=MiddlewareStack)
