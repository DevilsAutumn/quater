from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import msgspec
import pytest

from quater import Body, Cookie, Header, Quater, Request
from quater.actions.approval import action_arguments_hash
from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition, build_action_registry
from quater.exceptions import BadRequestError, UnauthorizedError
from quater.typing import ApprovalRequest, AuthContext, AuthRequest


class CreateUser(msgspec.Struct):
    name: str
    age: int


USER_PAYLOAD = Body(alias="user_payload")


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
        source="cli",
        surface_auth=allow_auth,
    )

    assert result.action == "create_user"
    assert result.source == "cli"
    assert result.entrypoint == "server"
    assert result.method == "POST"
    assert result.path == "/users"
    assert result.needs_approval is True
    assert result.approval_required is True
    assert result.subject == "cli"
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
            source="cli",
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
        source="cli",
        surface_auth=cli_auth,
    )

    assert calls == ["cli:cli:get_user", "route:cli:get_user"]
    assert response.body == (
        b'{"id":7,"source":"cli","action":"get_user","subject":"route"}'
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
        source="cli",
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
            source="cli",
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
            source="cli",
            surface_auth=allow_auth,
        )


@pytest.mark.asyncio
async def test_execute_action_uses_body_alias_for_action_arguments() -> None:
    app = Quater(cli_auth=allow_auth)

    @app.post("/users", cli=True, description="Create one user.")
    async def create_user(user: CreateUser = USER_PAYLOAD) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    response = await execute_action(
        action_for(app, "create_user"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"user_payload": {"name": "Ada", "age": 37}},
        source="cli",
        surface_auth=allow_auth,
    )

    assert response.body == b'{"name":"Ada","age":37}'


@pytest.mark.asyncio
async def test_action_header_and_cookie_arguments_are_available_to_handler() -> None:
    app = Quater(cli_auth=allow_auth)

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(
        request_id: str = Header(alias="X-Request-ID"),
        session_id: str = Cookie(alias="session"),
    ) -> dict[str, str]:
        return {"request_id": request_id, "session_id": session_id}

    response = await execute_action(
        action_for(app, "audit"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"request_id": "req_123", "session_id": "sess_123"},
        source="cli",
        surface_auth=allow_auth,
    )

    assert response.body == b'{"request_id":"req_123","session_id":"sess_123"}'


@pytest.mark.asyncio
async def test_action_cookie_arguments_reject_malformed_existing_cookie() -> None:
    app = Quater(cli_auth=allow_auth)
    handler_calls = 0

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(session_id: str = Cookie(alias="session")) -> dict[str, str]:
        nonlocal handler_calls
        handler_calls += 1
        return {"session_id": session_id}

    with pytest.raises(BadRequestError, match="Malformed Cookie header"):
        await execute_action(
            action_for(app, "audit"),
            Request(
                method="POST",
                path="/__quater__/actions/call",
                headers={"Cookie": "session=abc; $bad=x"},
            ),
            {"session_id": "sess_123"},
            source="cli",
            surface_auth=allow_auth,
        )

    assert handler_calls == 0


@pytest.mark.asyncio
async def test_action_optional_header_default_is_not_stringified() -> None:
    app = Quater(cli_auth=allow_auth)

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        return {"request_id": request_id}

    response = await execute_action(
        action_for(app, "audit"),
        Request(method="POST", path="/__quater__/actions/call"),
        {},
        source="cli",
        surface_auth=allow_auth,
    )

    assert response.body == b'{"request_id":null}'


@pytest.mark.asyncio
async def test_action_optional_header_null_is_not_stringified() -> None:
    app = Quater(cli_auth=allow_auth)

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        return {"request_id": request_id}

    response = await execute_action(
        action_for(app, "audit"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"request_id": None},
        source="cli",
        surface_auth=allow_auth,
    )

    assert response.body == b'{"request_id":null}'


@pytest.mark.asyncio
async def test_action_required_header_null_is_rejected() -> None:
    app = Quater(cli_auth=allow_auth)

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(request_id: str = Header(alias="X-Request-ID")) -> dict[str, str]:
        return {"request_id": request_id}

    with pytest.raises(BadRequestError, match="Invalid action argument: request_id"):
        await execute_action(
            action_for(app, "audit"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"request_id": None},
            source="cli",
            surface_auth=allow_auth,
        )


@pytest.mark.asyncio
async def test_action_header_arguments_do_not_bypass_route_auth() -> None:
    async def route_auth(ctx: AuthRequest) -> AuthContext | None:
        if ctx.headers.get("x-route-secret") == "server-secret":
            return AuthContext(subject="route")
        return None

    app = Quater(cli_auth=allow_auth)

    @app.get(
        "/private",
        cli=True,
        auth=route_auth,
        description="Read private state.",
    )
    async def private(
        route_secret: str = Header(alias="X-Route-Secret"),
    ) -> dict[str, str]:
        return {"route_secret": route_secret}

    with pytest.raises(UnauthorizedError, match="Unauthorized"):
        await execute_action(
            action_for(app, "private"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"route_secret": "server-secret"},
            source="cli",
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
