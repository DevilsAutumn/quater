"""Application and request state containers."""

from __future__ import annotations

from typing import Any


class State:
    """Small attribute container for application and request-local state.

    Use ``app.state`` for resources that should live with the application, and
    ``request.state`` for values that should last only for one request.
    """

    __slots__ = ("__dict__",)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
