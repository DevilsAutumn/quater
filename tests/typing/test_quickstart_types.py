from __future__ import annotations

from typing import Literal, assert_type

from quater import AuthContext, AuthRequest, Quater, Request, Response


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    token = ctx.headers.get("authorization")
    if token != "Bearer demo-token":
        return None
    return AuthContext(subject="demo-user")


app = Quater(
    docs_path="/docs",
    openapi_path="/openapi.json",
    mcp_docs_path="/mcp/docs",
    mcp_allowed_origins=["http://localhost:3000"],
    mcp_auth=authenticate,
)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get(
    "/users/{id:int}",
    tool=True,
    auth=authenticate,
    description="Fetch one user.",
)
async def get_user(id: int, request: Request) -> dict[str, object]:
    assert_type(id, int)
    assert_type(
        request.context.source,
        Literal["api", "mcp", "cli"],
    )
    assert_type(request.context.entrypoint, Literal["server", "local"])
    return {
        "id": id,
        "source": request.context.source,
        "tool": request.context.tool_name,
    }


async def dispatch_contract() -> None:
    response = await app.handle(Request(method="GET", path="/health"))
    assert_type(response, Response)
