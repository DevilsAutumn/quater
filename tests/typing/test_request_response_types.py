from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, assert_type

from quater import (
    BytesResponse,
    EmptyResponse,
    JSONResponse,
    RedirectResponse,
    Request,
    Response,
    StreamResponse,
    TextResponse,
)
from quater.response import normalize_response
from quater.typing import AuthContext, RequestContext


async def body_reader() -> bytes:
    return b"{}"


request = Request(
    method="POST",
    path="/items",
    headers={"authorization": "Bearer token"},
    query_string="page=1",
    body=body_reader,
    auth=AuthContext(subject="user_1"),
    context=RequestContext(source="mcp", tool_name="get_user"),
)


async def chunks() -> AsyncIterator[bytes]:
    yield b"chunk"


assert_type(request.method, str)
assert_type(request.path, str)
assert_type(request.auth, AuthContext | None)
assert_type(request.context, RequestContext)
assert_type(
    request.context.source,
    Literal["api", "mcp", "cli"],
)
assert_type(request.context.entrypoint, Literal["server", "local"])
assert_type(request.context.tool_name, str | None)
assert_type(request.context.action_name, str | None)
assert_type(request.headers["authorization"], str)
assert_type(request.query["page"], str)
assert_type(request.cookies.get("session"), str | None)
assert_type(JSONResponse({"ok": True}), JSONResponse)
assert_type(TextResponse("ok"), TextResponse)
assert_type(BytesResponse(b"ok"), BytesResponse)
assert_type(StreamResponse(chunks()), StreamResponse)
assert_type(RedirectResponse("/next"), RedirectResponse)
assert_type(EmptyResponse(), EmptyResponse)
assert_type(normalize_response({"ok": True}), Response)
