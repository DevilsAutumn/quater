from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import msgspec
import pytest

from quater import Quater, Request
from quater.actions.approval import action_arguments_hash
from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition, build_action_registry
from quater.exceptions import BadRequestError
from quater.typing import ApprovalRequest, AuthContext, AuthRequest


class CreateUser(msgspec.Struct):
    name: str
    age: int


async def allow_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject=ctx.context.source)


def action_for(app: Quater, name: str) -> ActionDefinition:
    action = build_action_registry(app.routes).get(name)
    assert action is not None
    return action


@pytest.mark.asyncio
async def test_preflight_validates_inputs_without_calling_handler_or_approval() -> None:
    handler_calls = 0
    approval_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        nonlocal approval_calls
        approval_calls += 1
        return True

    app = Quater(cli_auth=allow_auth, action_approval=approve)

    @app.post(
        "/users",
        cli=True,
        needs_approval=True,
        description="Create one user.",
    )
    async def create_user(user: CreateUser) -> dict[str, object]:
        nonlocal handler_calls
        handler_calls += 1
        return {"name": user.name, "age": user.age}

    result = await preflight_action(
        action_for(app, "create_user"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"user": {"name": "Ada", "age": 37}},
        source="remote_cli",
        surface_auth=allow_auth,
    )

    assert result.action == "create_user"
    assert result.source == "remote_cli"
    assert result.method == "POST"
    assert result.path == "/users"
    assert result.needs_approval is True
    assert result.approval_required is True
    assert result.subject == "remote_cli"
    assert result.arguments_hash.startswith("sha256:")
    assert handler_calls == 0
    assert approval_calls == 0


@pytest.mark.asyncio
async def test_preflight_rejects_invalid_body_shape_without_approval() -> None:
    approval_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        nonlocal approval_calls
        approval_calls += 1
        return True

    app = Quater(cli_auth=allow_auth, action_approval=approve)

    @app.post(
        "/users",
        cli=True,
        needs_approval=True,
        description="Create one user.",
    )
    async def create_user(user: CreateUser) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    with pytest.raises(BadRequestError, match="Invalid JSON body"):
        await preflight_action(
            action_for(app, "create_user"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"user": {"name": "Ada"}},
            source="remote_cli",
            surface_auth=allow_auth,
        )

    assert approval_calls == 0


@pytest.mark.asyncio
async def test_execute_action_runs_surface_auth_then_distinct_route_auth() -> None:
    calls: list[str] = []

    async def cli_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(f"cli:{ctx.context.source}:{ctx.context.action_name}")
        return AuthContext(subject="cli")

    async def route_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(f"route:{ctx.context.source}:{ctx.context.action_name}")
        return AuthContext(subject="route")

    app = Quater(cli_auth=cli_auth)

    @app.get(
        "/users/{id:int}",
        cli=True,
        auth=route_auth,
        description="Fetch one user.",
    )
    async def get_user(id: int, request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {
            "id": id,
            "source": request.context.source,
            "action": request.context.action_name,
            "subject": request.auth.subject,
        }

    response = await execute_action(
        action_for(app, "get_user"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"id": 7},
        source="remote_cli",
        surface_auth=cli_auth,
    )

    assert calls == ["cli:remote_cli:get_user", "route:remote_cli:get_user"]
    assert response.body == (
        b'{"id":7,"source":"remote_cli","action":"get_user","subject":"route"}'
    )


@pytest.mark.asyncio
async def test_execute_action_reruns_same_auth_hook_for_route_request() -> None:
    calls = 0
    paths: list[str] = []

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal calls
        calls += 1
        paths.append(ctx.path)
        return AuthContext(subject=ctx.context.source)

    app = Quater(cli_auth=authenticate)

    @app.get(
        "/users/{id:int}",
        cli=True,
        auth=authenticate,
        description="Fetch one user.",
    )
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await execute_action(
        action_for(app, "get_user"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"id": 7},
        source="remote_cli",
        surface_auth=authenticate,
    )

    assert calls == 2
    assert paths == ["/users/7", "/users/7"]
    assert response.body == b'{"id":7}'


@pytest.mark.asyncio
async def test_execute_action_validates_arguments_before_approval() -> None:
    approval_calls = 0
    handler_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        nonlocal approval_calls
        approval_calls += 1
        return True

    app = Quater(cli_auth=allow_auth, action_approval=approve)

    @app.post(
        "/users",
        cli=True,
        needs_approval=True,
        description="Create one user.",
    )
    async def create_user(user: CreateUser) -> dict[str, object]:
        nonlocal handler_calls
        handler_calls += 1
        return {"name": user.name, "age": user.age}

    with pytest.raises(BadRequestError, match="Invalid JSON body"):
        await execute_action(
            action_for(app, "create_user"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"user": {"name": "Ada"}},
            source="remote_cli",
            surface_auth=allow_auth,
            approval_hook=approve,
            approval_token="approved",
        )

    assert approval_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_execute_action_rejects_non_json_body_argument() -> None:
    app = Quater(cli_auth=allow_auth)

    @app.post("/users", cli=True, description="Create one user.")
    async def create_user(user: object) -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(BadRequestError, match="Invalid action argument: user"):
        await execute_action(
            action_for(app, "create_user"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"user": object()},
            source="remote_cli",
            surface_auth=allow_auth,
        )


def test_action_argument_hash_is_stable_for_mapping_order() -> None:
    first = action_arguments_hash(
        "users.create",
        {"user": {"name": "Ada", "age": 37}, "send_email": True},
    )
    second = action_arguments_hash(
        "users.create",
        {"send_email": True, "user": {"age": 37, "name": "Ada"}},
    )

    assert first == second


def test_action_argument_hash_rejects_non_string_mapping_keys() -> None:
    arguments = cast(Mapping[str, object], {1: "one"})

    with pytest.raises(BadRequestError, match="Invalid action arguments"):
        action_arguments_hash("users.create", arguments)
