"""Public typing helpers for framework extension points."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from quater.request import Request

RequestSource: TypeAlias = Literal["api", "mcp", "cli"]
RequestEntrypoint: TypeAlias = Literal["server", "local"]

# Every request surface, in a stable order for messages and iteration.
SURFACES: tuple[RequestSource, ...] = ("api", "mcp", "cli")


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
class AuthContext:
    """Authenticated identity returned by an authenticator.

    ``subject`` should be a stable user, service, or agent id. ``metadata`` is
    for small request-scoped values your app wants to carry into the handler.
    ``payload`` carries an app object the authenticator already loaded (for
    example the ``User`` row) so a handler can read it back through a typed
    resource without a second lookup. Quater never inspects ``payload``; keep
    your app's domain type out of the framework contract.
    """

    subject: str
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)
    payload: object = None


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


# An authenticator receives the request. Use ``await request.resolve(resource)``
# inside it when a request-scoped resource is needed after cheap checks pass.
# Handlers can still inject the same resource through ``Annotated[T, resource]``.
Authenticator: TypeAlias = Callable[["Request"], Awaitable[AuthContext | None]]
ActionApproval: TypeAlias = Callable[[ApprovalRequest], Awaitable[bool]]
LifespanHook: TypeAlias = Callable[[], Awaitable[None]]

__all__ = [
    "ActionApproval",
    "Authenticator",
    "ApprovalRequest",
    "AuthContext",
    "LifespanHook",
    "RequestContext",
    "RequestEntrypoint",
    "RequestSource",
]
