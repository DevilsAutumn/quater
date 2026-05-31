from __future__ import annotations

from typing import Literal, assert_type

from quater import (
    AccessLogEvent,
    AccessLogHook,
    AuthConfig,
    AuthContext,
    Quater,
    Request,
)
from quater.response import Response
from quater.typing import LifespanHook, RequestSource


async def authenticate(ctx: Request) -> AuthContext | None:
    token = ctx.headers.get("authorization")
    if token is None:
        return None
    return AuthContext(subject=token)


async def log_access(event: AccessLogEvent) -> None:
    assert_type(event.request_id, str)
    assert_type(event.source, Literal["api", "mcp", "cli"])
    assert_type(event.entrypoint, Literal["server", "local"])


app = Quater(
    allowed_hosts=["api.example.com"],
    access_logger=log_access,
    auth=[AuthConfig(authenticate, surfaces=["api"])],
)


@app.get("/me")
async def me(request: Request) -> dict[str, str]:
    assert request.auth is not None
    return {"subject": request.auth.subject}


@app.on_startup
async def startup() -> None:
    return None


@app.on_shutdown
async def shutdown() -> None:
    return None


async def dispatch_contract() -> None:
    response = await app.handle(Request(method="GET", path="/missing"))
    assert_type(response, Response)


assert_type(app.routes[0].public, tuple[RequestSource, ...])
assert_type(startup, LifespanHook)
assert_type(shutdown, LifespanHook)
assert_type(app.config.allowed_hosts, tuple[str, ...])
assert_type(app.access_logger, AccessLogHook | None)
