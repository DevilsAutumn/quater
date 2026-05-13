"""Public typing helpers for framework extension points."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias

RequestSource: TypeAlias = Literal["api", "mcp", "cli"]
RequestEntrypoint: TypeAlias = Literal["server", "local"]


def _empty_str_map() -> Mapping[str, str]:
    return MappingProxyType({})


def _empty_metadata() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(slots=True, frozen=True)
class RequestContext:
    """Call-source metadata attached to a request.

    ``source`` tells whether the call came through the HTTP API, MCP, or CLI.
    ``entrypoint`` separates hosted server requests from local in-process CLI
    calls.
    """

    source: RequestSource = "api"
    entrypoint: RequestEntrypoint = "server"
    request_id: str | None = None
    tool_name: str | None = None
    action_name: str | None = None


@dataclass(slots=True, frozen=True)
class AuthRequest:
    """Request view passed to an auth hook.

    It contains the fields auth code usually needs: method, path, normalized
    headers, and Quater call context.
    """

    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=_empty_str_map)
    context: RequestContext = field(default_factory=RequestContext)


@dataclass(slots=True, frozen=True)
class AuthContext:
    """Authenticated identity returned by an auth hook.

    ``subject`` should be a stable user, service, or agent id. ``metadata`` is
    for small request-scoped values your app wants to carry into the handler.
    """

    subject: str
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(slots=True, frozen=True)
class ApprovalRequest:
    """Input passed to an approval hook for protected tools and CLI actions.

    The arguments hash is computed after binding and validation. Use it to
    match a prior approval to the exact action arguments being executed.
    """

    action: str
    arguments_hash: str
    token: str
    auth: AuthContext | None = None
    context: RequestContext = field(default_factory=RequestContext)


Authenticate: TypeAlias = Callable[[AuthRequest], Awaitable[AuthContext | None]]
ActionApproval: TypeAlias = Callable[[ApprovalRequest], Awaitable[bool]]
LifespanHook: TypeAlias = Callable[[], Awaitable[None]]

__all__ = [
    "ActionApproval",
    "Authenticate",
    "ApprovalRequest",
    "AuthContext",
    "AuthRequest",
    "LifespanHook",
    "RequestContext",
    "RequestEntrypoint",
    "RequestSource",
]
