from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import msgspec
import pytest

from quater import AuthConfig, Body, Cookie, Header, Quater, Request
from quater.actions.approval import action_arguments_hash
from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition, build_action_registry
from quater.exceptions import BadRequestError
from quater.typing import ApprovalRequest, AuthContext


class CreateUser(msgspec.Struct):
    name: str
    age: int


USER_PAYLOAD = Body(alias="user_payload")


async def allow_auth(ctx: Request) -> AuthContext | None:
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

    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])], action_approval=approve
    )

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
        Request(
            method="POST",
            path="/__quater__/actions/call",
            auth=AuthContext(subject="cli"),
        ),
        {"user": {"name": "Ada", "age": 37}},
        source="cli",
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

    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])], action_approval=approve
    )

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
        )

    assert approval_calls == 0


@pytest.mark.asyncio
async def test_execute_action_validates_arguments_before_approval() -> None:
    approval_calls = 0
    handler_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        nonlocal approval_calls
        approval_calls += 1
        return True

    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])], action_approval=approve
    )

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
            approval_hook=approve,
            approval_token="approved",
        )

    assert approval_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_execute_action_rejects_non_json_body_argument() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.post("/users", cli=True, description="Create one user.")
    async def create_user(user: object) -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(BadRequestError, match="Invalid action argument: user"):
        await execute_action(
            action_for(app, "create_user"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"user": object()},
            source="cli",
        )


@pytest.mark.asyncio
async def test_execute_action_uses_body_alias_for_action_arguments() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.post("/users", cli=True, description="Create one user.")
    async def create_user(user: CreateUser = USER_PAYLOAD) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    response = await execute_action(
        action_for(app, "create_user"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"user_payload": {"name": "Ada", "age": 37}},
        source="cli",
    )

    assert response.body == b'{"name":"Ada","age":37}'


@pytest.mark.asyncio
async def test_action_header_and_cookie_arguments_are_available_to_handler() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

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
    )

    assert response.body == b'{"request_id":"req_123","session_id":"sess_123"}'


@pytest.mark.asyncio
async def test_action_cookie_arguments_reject_malformed_existing_cookie() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])
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
        )

    assert handler_calls == 0


@pytest.mark.asyncio
async def test_action_optional_header_default_is_not_stringified() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

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
    )

    assert response.body == b'{"request_id":null}'


@pytest.mark.asyncio
async def test_action_optional_header_null_is_not_stringified() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

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
    )

    assert response.body == b'{"request_id":null}'


@pytest.mark.asyncio
async def test_action_required_header_null_is_rejected() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(request_id: str = Header(alias="X-Request-ID")) -> dict[str, str]:
        return {"request_id": request_id}

    with pytest.raises(BadRequestError, match="Invalid action argument: request_id"):
        await execute_action(
            action_for(app, "audit"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"request_id": None},
            source="cli",
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
