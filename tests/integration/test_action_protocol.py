from __future__ import annotations

import json

import pytest

from quater import AuthContext, AuthRequest, Quater, Request, Response
from quater.protocol.actions import (
    ACTIONS_MANIFEST_PATH,
    ACTIONS_RPC_PATH,
    MAX_ACTION_RESPONSE_BYTES,
)
from quater.typing import ApprovalRequest


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer cli":
        return None
    return AuthContext(subject="cli-user")


def authed_headers() -> dict[str, str]:
    return {
        "authorization": "Bearer cli",
        "content-type": "application/json",
    }


async def action_rpc(
    app: Quater,
    body: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    response = await app.handle(
        Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers=headers or authed_headers(),
            body=json.dumps(body).encode("utf-8"),
        )
    )
    return response.status_code, json.loads(response.body)


def require_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
async def test_remote_action_endpoints_are_absent_without_cli_actions() -> None:
    app = Quater()

    manifest = await app.handle(Request(method="GET", path=ACTIONS_MANIFEST_PATH))
    rpc = await app.handle(Request(method="POST", path=ACTIONS_RPC_PATH))

    assert manifest.status_code == 404
    assert rpc.status_code == 404


@pytest.mark.asyncio
async def test_remote_action_manifest_requires_cli_auth() -> None:
    app = Quater(cli_auth=authenticate)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(Request(method="GET", path=ACTIONS_MANIFEST_PATH))

    assert response.status_code == 401
    assert b"get_user" not in response.body


@pytest.mark.asyncio
async def test_remote_action_manifest_lists_only_cli_actions() -> None:
    app = Quater(cli_auth=authenticate)

    @app.get("/internal")
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(
        Request(
            method="GET",
            path=ACTIONS_MANIFEST_PATH,
            headers=authed_headers(),
        )
    )

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["protocol"] == "quater-actions.v1"
    actions = body["actions"]
    assert len(actions) == 1
    assert actions[0]["name"] == "get_user"


@pytest.mark.asyncio
async def test_remote_action_manifest_auth_sees_cli_http_context() -> None:
    seen: list[AuthRequest] = []

    async def cli_auth(ctx: AuthRequest) -> AuthContext | None:
        seen.append(ctx)
        if ctx.headers.get("authorization") == "Bearer cli":
            return AuthContext(subject="cli-user")
        return None

    app = Quater(cli_auth=cli_auth)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(
        Request(
            method="GET",
            path=ACTIONS_MANIFEST_PATH,
            headers=authed_headers(),
        )
    )

    assert response.status_code == 200
    assert len(seen) == 1
    assert seen[0].context.source == "cli"
    assert seen[0].context.entrypoint == "server"
    assert seen[0].context.action_name is None


@pytest.mark.asyncio
async def test_remote_action_rpc_requires_cli_auth_before_handler_runs() -> None:
    calls = 0
    app = Quater(cli_auth=authenticate)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"id": id}

    response = await app.handle(
        Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers={"content-type": "application/json"},
            body=b'{"action":"get_user","arguments":{"id":7}}',
        )
    )

    assert response.status_code == 401
    assert calls == 0


@pytest.mark.asyncio
async def test_remote_action_rpc_auth_sees_cli_http_context() -> None:
    seen: list[AuthRequest] = []

    async def cli_auth(ctx: AuthRequest) -> AuthContext | None:
        seen.append(ctx)
        if ctx.headers.get("authorization") == "Bearer cli":
            return AuthContext(subject="cli-user")
        return None

    app = Quater(cli_auth=cli_auth)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        return {
            "id": id,
            "source": request.context.source,
            "entrypoint": request.context.entrypoint,
            "action": request.context.action_name,
        }

    status, body = await action_rpc(
        app,
        {"action": "get_user", "arguments": {"id": 7}},
    )

    assert status == 200
    assert body["body"] == {
        "id": 7,
        "source": "cli",
        "entrypoint": "server",
        "action": "get_user",
    }
    assert len(seen) == 1
    assert seen[0].context.source == "cli"
    assert seen[0].context.entrypoint == "server"
    assert seen[0].context.action_name is None


@pytest.mark.asyncio
async def test_remote_action_rpc_cannot_call_non_cli_route() -> None:
    app = Quater(cli_auth=authenticate)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    status, body = await action_rpc(app, {"action": "health", "arguments": {}})

    assert status == 404
    assert body["error"] == {"code": "unknown_action", "message": "Unknown action"}


@pytest.mark.asyncio
async def test_remote_action_dry_run_validates_without_handler_or_approval() -> None:
    calls = 0
    approval_calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        nonlocal approval_calls
        approval_calls += 1
        return True

    app = Quater(cli_auth=authenticate, action_approval=approve)

    @app.post(
        "/users/{id:int}/lock",
        cli=True,
        needs_approval=True,
        description="Lock one user.",
    )
    async def lock_user(id: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"id": id}

    status, body = await action_rpc(
        app,
        {
            "action": "lock_user",
            "arguments": {"id": 7},
            "dry_run": True,
        },
    )

    assert status == 200
    assert body["dry_run"] is True
    assert body["approval_required"] is True
    assert body["path"] == "/users/7/lock"
    assert calls == 0
    assert approval_calls == 0


@pytest.mark.asyncio
async def test_remote_action_requires_approval_token_before_handler_runs() -> None:
    calls = 0

    async def approve(ctx: ApprovalRequest) -> bool:
        return True

    app = Quater(cli_auth=authenticate, action_approval=approve)

    @app.post(
        "/users/{id:int}/lock",
        cli=True,
        needs_approval=True,
        description="Lock one user.",
    )
    async def lock_user(id: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"id": id}

    status, body = await action_rpc(
        app,
        {"action": "lock_user", "arguments": {"id": 7}},
    )

    assert status == 409
    error = require_object(body["error"])
    assert error["code"] == "approval_required"
    assert calls == 0


@pytest.mark.asyncio
async def test_remote_action_runs_after_valid_approval() -> None:
    seen: list[ApprovalRequest] = []

    async def approve(ctx: ApprovalRequest) -> bool:
        seen.append(ctx)
        return ctx.token == "approved"

    app = Quater(cli_auth=authenticate, action_approval=approve)

    @app.post(
        "/users/{id:int}/lock",
        cli=True,
        needs_approval=True,
        description="Lock one user.",
    )
    async def lock_user(id: int, request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {
            "id": id,
            "source": request.context.source,
            "entrypoint": request.context.entrypoint,
            "action": request.context.action_name,
            "subject": request.auth.subject,
        }

    status, body = await action_rpc(
        app,
        {
            "action": "lock_user",
            "arguments": {"id": 7},
            "approval_token": "approved",
        },
    )

    assert status == 200
    assert body == {
        "ok": True,
        "status_code": 200,
        "body": {
            "id": 7,
            "source": "cli",
            "entrypoint": "server",
            "action": "lock_user",
            "subject": "cli-user",
        },
    }
    assert len(seen) == 1
    assert seen[0].context.source == "cli"
    assert seen[0].context.entrypoint == "server"
    assert seen[0].auth is not None
    assert seen[0].auth.subject == "cli-user"


@pytest.mark.asyncio
async def test_remote_action_handler_errors_do_not_leak_details() -> None:
    app = Quater(cli_auth=authenticate)

    @app.post("/danger", cli=True, description="Run dangerous action.")
    async def danger() -> dict[str, bool]:
        raise RuntimeError("database password is secret")

    status, body = await action_rpc(app, {"action": "danger", "arguments": {}})

    assert status == 500
    assert body["error"] == {"code": "action_failed", "message": "Action call failed"}
    assert "secret" not in json.dumps(body)


@pytest.mark.asyncio
async def test_remote_action_rejects_oversized_response() -> None:
    app = Quater(cli_auth=authenticate)

    @app.get("/large", cli=True, description="Return a large payload.")
    async def large() -> Response:
        return Response(b"x" * (MAX_ACTION_RESPONSE_BYTES + 1))

    status, body = await action_rpc(app, {"action": "large", "arguments": {}})

    assert status == 502
    assert body["error"] == {
        "code": "response_too_large",
        "message": "Response too large",
    }


@pytest.mark.asyncio
async def test_remote_action_response_limit_uses_app_config() -> None:
    app = Quater(cli_auth=authenticate, max_action_response_size=4)

    @app.get("/small-limit", cli=True, description="Return a small oversized payload.")
    async def small_limit() -> Response:
        return Response(b"hello")

    status, body = await action_rpc(
        app,
        {"action": "small_limit", "arguments": {}},
    )

    assert status == 502
    assert body["error"] == {
        "code": "response_too_large",
        "message": "Response too large",
    }


@pytest.mark.asyncio
async def test_remote_action_rejects_bad_payload_shapes() -> None:
    app = Quater(cli_auth=authenticate)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    status, body = await action_rpc(
        app,
        {"action": "get_user", "arguments": [], "dry_run": "yes"},
    )

    assert status == 400
    assert body["error"] == {
        "code": "invalid_arguments",
        "message": "Invalid arguments",
    }


@pytest.mark.asyncio
async def test_normal_api_auth_is_not_bypassed_by_action_support() -> None:
    async def route_auth(ctx: AuthRequest) -> AuthContext | None:
        if ctx.headers.get("authorization") == "Bearer route":
            return AuthContext(subject="api-user")
        return None

    app = Quater(cli_auth=authenticate)

    @app.get(
        "/private",
        auth=route_auth,
        cli=True,
        description="Read private data.",
    )
    async def private(request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {"subject": request.auth.subject}

    response = await app.handle(Request(method="GET", path="/private"))

    assert response.status_code == 401
    assert b"api-user" not in response.body
