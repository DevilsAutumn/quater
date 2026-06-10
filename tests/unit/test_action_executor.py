from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

import msgspec
import pytest

from quater import AuthConfig, Body, Cookie, Header, Quater, Request, Resource
from quater.actions.approval import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    action_arguments_hash,
)
from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition, build_action_registry
from quater.exceptions import BadRequestError
from quater.typing import ApprovalRequest, AuthContext


class CreateUser(msgspec.Struct):
    name: str
    age: int


USER_PAYLOAD = Body(alias="user_payload")
DEFAULT_PAYLOAD = Body({"x": 7}, alias="payload_alias")


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
        authorization: str = Header(),
        request_id: str = Header(alias="X-Request-ID"),
        session_id: str = Cookie(alias="session"),
    ) -> dict[str, str]:
        return {
            "authorization": authorization,
            "request_id": request_id,
            "session_id": session_id,
        }

    response = await execute_action(
        action_for(app, "audit"),
        Request(method="POST", path="/__quater__/actions/call"),
        {
            "authorization": "Bearer action-token",
            "request_id": "req_123",
            "session_id": "sess_123",
        },
        source="cli",
    )

    assert (
        response.body
        == b'{"authorization":"Bearer action-token","request_id":"req_123",'
        b'"session_id":"sess_123"}'
    )


@pytest.mark.asyncio
async def test_action_cookie_argument_with_reserved_name_reaches_handler() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(path: str = Cookie()) -> dict[str, str]:
        return {"path": path}

    # "path" is a Set-Cookie attribute word; building the synthetic request must
    # not drop it, so MCP and CLI stay at parity with HTTP.
    response = await execute_action(
        action_for(app, "audit"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"path": "/admin"},
        source="cli",
    )

    assert response.body == b'{"path":"/admin"}'


@pytest.mark.asyncio
async def test_action_requests_do_not_inherit_transport_headers_or_cookies() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(
        authorization: str | None = Header(default=None),
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
        session_id: str | None = Cookie(default=None, alias="session"),
    ) -> dict[str, object]:
        return {
            "authorization": authorization,
            "request_id": request_id,
            "session_id": session_id,
        }

    response = await execute_action(
        action_for(app, "audit"),
        Request(
            method="POST",
            path="/__quater__/actions/call",
            headers={
                "authorization": "Bearer surface-token",
                "cookie": "session=outer-cookie",
                "x-request-id": "outer-request",
            },
        ),
        {},
        source="cli",
    )

    assert (
        response.body == b'{"authorization":null,"request_id":null,"session_id":null}'
    )


@pytest.mark.asyncio
async def test_action_cookie_arguments_ignore_malformed_transport_cookie() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])
    handler_calls = 0

    @app.get("/audit", cli=True, description="Read audit state.")
    async def audit(session_id: str = Cookie(alias="session")) -> dict[str, str]:
        nonlocal handler_calls
        handler_calls += 1
        return {"session_id": session_id}

    response = await execute_action(
        action_for(app, "audit"),
        Request(
            method="POST",
            path="/__quater__/actions/call",
            headers={"Cookie": "session=abc; $bad=x"},
        ),
        {"session_id": "sess_123"},
        source="cli",
    )

    assert response.body == b'{"session_id":"sess_123"}'
    assert handler_calls == 1


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


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["mcp", "cli"])
@pytest.mark.parametrize("user_id", ["-5", "+7", "1_000", "١٢٣", " 7", "7\n"])
async def test_action_int_path_argument_rejects_non_canonical_values(
    source: Literal["mcp", "cli"],
    user_id: str,
) -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])
    handler_calls = 0

    @app.get("/users/{id:int}", tool=True, cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        nonlocal handler_calls
        handler_calls += 1
        return {"id": id}

    with pytest.raises(BadRequestError, match="Invalid path argument: id"):
        await execute_action(
            action_for(app, "get_user"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"id": user_id},
            source=source,
        )

    assert handler_calls == 0


@pytest.mark.asyncio
async def test_argument_hash_uses_bound_scalar_values_and_defaults() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int, include_email: bool = False) -> dict[str, object]:
        return {"id": id, "include_email": include_email}

    action = action_for(app, "get_user")
    request = Request(method="POST", path="/__quater__/actions/call")

    missing_default = await preflight_action(
        action,
        request,
        {"id": "7"},
        source="cli",
    )
    explicit_default = await preflight_action(
        action,
        request,
        {"id": 7, "include_email": False},
        source="cli",
    )
    string_values = await preflight_action(
        action,
        request,
        {"id": "7", "include_email": "false"},
        source="cli",
    )
    different_call = await preflight_action(
        action,
        request,
        {"id": 7, "include_email": True},
        source="cli",
    )

    assert missing_default.arguments_hash == explicit_default.arguments_hash
    assert missing_default.arguments_hash == string_values.arguments_hash
    assert missing_default.arguments_hash == action_arguments_hash(
        "get_user",
        {"id": 7, "include_email": False},
    )
    assert missing_default.arguments_hash != different_call.arguments_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("ratio", ["nan", "inf", "-inf", "infinity"])
async def test_argument_hash_rejects_non_finite_bound_float_values(
    ratio: str,
) -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get("/risk", cli=True, description="Read risk.")
    async def risk(ratio: float | None = None) -> dict[str, object]:
        return {"ratio": ratio}

    action = action_for(app, "risk")
    request = Request(method="POST", path="/__quater__/actions/call")
    missing = await preflight_action(action, request, {}, source="cli")

    assert missing.arguments_hash == action_arguments_hash("risk", {"ratio": None})
    with pytest.raises(BadRequestError, match="Invalid float query parameter: ratio"):
        await preflight_action(action, request, {"ratio": ratio}, source="cli")


@pytest.mark.asyncio
async def test_approval_hook_receives_preflight_bound_argument_hash() -> None:
    seen_hashes: list[str] = []

    async def approve(ctx: ApprovalRequest) -> bool:
        seen_hashes.append(ctx.arguments_hash)
        return True

    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])],
        action_approval=approve,
    )

    @app.post(
        "/users/{id:int}/lock",
        cli=True,
        needs_approval=True,
        description="Lock one user.",
    )
    async def lock_user(id: int, notify: bool = False) -> dict[str, object]:
        return {"id": id, "notify": notify}

    action = action_for(app, "lock_user")
    request = Request(
        method="POST",
        path="/__quater__/actions/call",
        auth=AuthContext(subject="cli"),
    )
    dry_run = await preflight_action(
        action,
        request,
        {"id": 7, "notify": False},
        source="cli",
    )

    response = await execute_action(
        action,
        request,
        {"id": "7", "notify": "false"},
        source="cli",
        approval_hook=approve,
        approval_token="approved",
    )

    assert response.body == b'{"id":7,"notify":false}'
    assert seen_hashes == [dry_run.arguments_hash]


@pytest.mark.asyncio
async def test_argument_hash_includes_bound_body_default_under_input_alias() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.post("/items", cli=True, description="Create one item.")
    async def create_item(
        payload: dict[str, int] = DEFAULT_PAYLOAD,
    ) -> dict[str, int]:
        return payload

    action = action_for(app, "create_item")
    request = Request(method="POST", path="/__quater__/actions/call")

    missing_default = await preflight_action(action, request, {}, source="cli")
    explicit_default = await preflight_action(
        action,
        request,
        {"payload_alias": {"x": 7}},
        source="cli",
    )
    different_call = await preflight_action(
        action,
        request,
        {"payload_alias": {"x": 8}},
        source="cli",
    )

    assert missing_default.arguments_hash == explicit_default.arguments_hash
    assert missing_default.arguments_hash == action_arguments_hash(
        "create_item",
        {"payload_alias": {"x": 7}},
    )
    assert missing_default.arguments_hash != different_call.arguments_hash


@pytest.mark.asyncio
async def test_argument_hash_excludes_request_and_resource_values() -> None:
    resource_events: list[str] = []

    class Session:
        pass

    async def provider() -> Session:
        resource_events.append("open")
        return Session()

    async def approve(ctx: ApprovalRequest) -> bool:
        return True

    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])],
        action_approval=approve,
    )

    @app.post(
        "/users/{id:int}/lock",
        cli=True,
        needs_approval=True,
        inject={"session": Resource(provider)},
        description="Lock one user.",
    )
    async def lock_user(
        id: int,
        request: Request,
        session: Session,
    ) -> dict[str, object]:
        return {"id": id, "source": request.context.source}

    action = action_for(app, "lock_user")
    request = Request(method="POST", path="/__quater__/actions/call")
    dry_run = await preflight_action(action, request, {"id": "7"}, source="cli")

    assert dry_run.arguments_hash == action_arguments_hash("lock_user", {"id": 7})
    assert resource_events == []

    with pytest.raises(ApprovalRequiredError) as exc_info:
        await execute_action(action, request, {"id": "7"}, source="cli")

    assert exc_info.value.arguments_hash == dry_run.arguments_hash
    assert resource_events == []


@pytest.mark.asyncio
async def test_approval_denied_without_hook_uses_bound_argument_hash() -> None:
    async def approve(ctx: ApprovalRequest) -> bool:
        return True

    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])],
        action_approval=approve,
    )

    @app.post(
        "/users/{id:int}/lock",
        cli=True,
        needs_approval=True,
        description="Lock one user.",
    )
    async def lock_user(id: int, notify: bool = False) -> dict[str, object]:
        return {"id": id, "notify": notify}

    action = action_for(app, "lock_user")
    request = Request(method="POST", path="/__quater__/actions/call")
    dry_run = await preflight_action(
        action,
        request,
        {"id": 7, "notify": False},
        source="cli",
    )

    with pytest.raises(ApprovalDeniedError) as exc_info:
        await execute_action(
            action,
            request,
            {"id": "7", "notify": "false"},
            source="cli",
            approval_hook=None,
            approval_token="approved",
        )

    assert exc_info.value.arguments_hash == dry_run.arguments_hash


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
