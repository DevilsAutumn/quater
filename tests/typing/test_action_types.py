from __future__ import annotations

from typing import assert_type

from quater import (
    ActionApproval,
    ApprovalRequest,
    AuthConfig,
    AuthContext,
    Quater,
    Request,
)
from quater.actions.registry import (
    ActionDefinition,
    ActionRegistry,
    build_action_registry,
)
from quater.typing import RequestContext


async def authenticate(ctx: Request) -> AuthContext | None:
    assert_type(ctx.context, RequestContext)
    return AuthContext(subject=ctx.context.source)


async def approve(ctx: ApprovalRequest) -> bool:
    assert_type(ctx.action, str)
    assert_type(ctx.arguments_hash, str)
    assert_type(ctx.token, str)
    assert_type(ctx.auth, AuthContext | None)
    assert_type(ctx.context, RequestContext)
    return True


app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])], action_approval=approve)


@app.post(
    "/invoices/{id:int}/paid",
    cli=True,
    needs_approval=True,
    description="Mark an invoice as paid.",
)
async def mark_paid(id: int) -> dict[str, int]:
    return {"id": id}


registry = build_action_registry(app.routes)

assert_type(app.action_approval, ActionApproval | None)
assert_type(registry, ActionRegistry)
assert_type(registry.get("mark_paid"), ActionDefinition | None)
