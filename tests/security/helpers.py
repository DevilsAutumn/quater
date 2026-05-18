from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from quater import AuthContext, AuthRequest, Quater, Request
from quater.protocol.actions import ACTIONS_MANIFEST_PATH, ACTIONS_RPC_PATH
from quater.response import Response
from quater.serialization import dumps_json, loads_json
from quater.testing import TestResponse

SURFACE_TOKEN = "surface-token"
ROUTE_TOKEN = "route-token"
SECRET_MARKER = "super-secret-token-value"
INTERNAL_PATH_MARKER = "/Volumes/MacExtended/python-projects/quater"


async def allow_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject=f"{ctx.context.source}-subject")


async def deny_auth(_ctx: AuthRequest) -> AuthContext | None:
    return None


async def surface_token_auth(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") == f"Bearer {SURFACE_TOKEN}":
        return AuthContext(subject="surface-user")
    return None


async def route_token_auth(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("x-route-auth") == ROUTE_TOKEN:
        return AuthContext(subject="route-user")
    return None


async def exploding_auth(_ctx: AuthRequest) -> AuthContext | None:
    raise RuntimeError(f"{SECRET_MARKER} at {INTERNAL_PATH_MARKER}/settings.py")


def decoded_object(body: bytes) -> dict[str, object]:
    value = loads_json(body)
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def decoded_test_object(response: TestResponse) -> dict[str, object]:
    value = response.json()
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


async def remote_action_manifest(
    app: Quater,
    *,
    headers: Mapping[str, str] | None = None,
) -> Response:
    return await app.handle(
        Request(
            method="GET",
            path=ACTIONS_MANIFEST_PATH,
            headers=headers or {},
        )
    )


async def remote_action_call(
    app: Quater,
    payload: Mapping[str, object],
    *,
    headers: Mapping[str, str] | None = None,
) -> Response:
    return await app.handle(
        Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers={
                "content-type": "application/json",
                **dict(headers or {}),
            },
            body=dumps_json(dict(payload)),
        )
    )


def surface_headers(*, route: bool = False) -> dict[str, str]:
    headers = {
        "authorization": f"Bearer {SURFACE_TOKEN}",
        "content-type": "application/json",
    }
    if route:
        headers["x-route-auth"] = ROUTE_TOKEN
    return headers
