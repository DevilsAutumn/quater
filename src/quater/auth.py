"""Central auth hook execution."""

from __future__ import annotations

from types import MappingProxyType

from quater.exceptions import UnauthorizedError
from quater.request import Request
from quater.typing import AuthContext, Authenticate, AuthRequest


async def authenticate_request(
    authenticate: Authenticate,
    request: Request,
) -> AuthContext:
    context = await authenticate(build_auth_request(request))
    if context is None or not isinstance(context, AuthContext):
        raise UnauthorizedError
    request.auth = context
    return context


def build_auth_request(request: Request) -> AuthRequest:
    return AuthRequest(
        method=request.method,
        path=request.path,
        headers=MappingProxyType(dict(request.headers.items())),
        context=request.context,
    )
