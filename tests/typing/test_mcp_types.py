from __future__ import annotations

from typing import assert_type

from quater import AuthConfig, Quater, Request, ToolAuditEvent
from quater.tools.audit import AuditHook
from quater.tools.registry import ToolRegistry, build_tool_registry
from quater.typing import AuthContext, RequestContext


async def authenticate(ctx: Request) -> AuthContext | None:
    assert_type(ctx.context, RequestContext)
    return AuthContext(subject=ctx.context.source)


async def audit(event: ToolAuditEvent) -> None:
    assert_type(event.tool_name, str)
    assert_type(event.subject, str | None)
    assert_type(event.success, bool)
    assert_type(event.arguments["id"], object)


app = Quater(
    mcp_allowed_origins=["https://app.example.com"],
    auth=[AuthConfig(authenticate, surfaces=["mcp"])],
    mcp_audit=audit,
)


@app.get("/me", tool=True, description="Read current user.")
async def me() -> dict[str, bool]:
    return {"ok": True}


registry = build_tool_registry(app.routes)

assert_type(app.mcp_audit, AuditHook | None)
assert_type(app.config.mcp_allowed_origins, tuple[str, ...])
assert_type(app.config.docs_path, str | None)
assert_type(app.config.openapi_path, str | None)
assert_type(app.config.mcp_docs_path, str | None)
assert_type(registry, ToolRegistry)
