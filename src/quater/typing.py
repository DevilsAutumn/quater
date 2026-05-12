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
    """Small per-call context shared by HTTP APIs, MCP, and CLI actions."""

    source: RequestSource = "api"
    entrypoint: RequestEntrypoint = "server"
    request_id: str | None = None
    tool_name: str | None = None
    action_name: str | None = None


@dataclass(slots=True, frozen=True)
class AuthRequest:
    """Small request view passed to the future central auth hook."""

    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=_empty_str_map)
    context: RequestContext = field(default_factory=RequestContext)


@dataclass(slots=True, frozen=True)
class AuthContext:
    """Authenticated subject information returned by a user auth hook."""

    subject: str
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(slots=True, frozen=True)
class ApprovalRequest:
    """Request passed to an approval hook before a protected action runs."""

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
