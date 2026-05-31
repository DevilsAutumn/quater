from __future__ import annotations

from quater import AuthConfig, AuthContext, Quater, Request, ToolAuditEvent


async def authenticate(request: Request) -> AuthContext | None:
    token = request.headers.get("authorization")
    if token != "Bearer demo-token":
        return None
    return AuthContext(
        subject="demo-user",
        metadata={"source": request.context.source},
    )


async def audit_tool_call(event: ToolAuditEvent) -> None:
    return None


app = Quater(
    mcp_allowed_origins=["http://localhost:3000"],
    auth=[AuthConfig(authenticate, surfaces=["api", "mcp"])],
    mcp_audit=audit_tool_call,
)


@app.get("/profile")
async def profile(request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {
        "subject": request.auth.subject,
        "source": request.context.source,
    }


@app.get(
    "/users/{id:int}",
    tool=True,
    description="Fetch one user by id.",
)
async def get_user(id: int, request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {
        "id": id,
        "subject": request.auth.subject,
        "source": request.context.source,
        "tool": request.context.tool_name,
    }
