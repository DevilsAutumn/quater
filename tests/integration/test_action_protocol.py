from __future__ import annotations

import json

import pytest

from quater import (
    AuthConfig,
    AuthContext,
    Cookie,
    Header,
    Quater,
    Request,
    Response,
    TextResponse,
)
from quater.protocol.actions import (
    ACTIONS_MANIFEST_PATH,
    ACTIONS_RPC_PATH,
    MAX_ACTION_RESPONSE_BYTES,
)
from quater.typing import ApprovalRequest


async def authenticate(ctx: Request) -> AuthContext | None:
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
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(Request(method="GET", path=ACTIONS_MANIFEST_PATH))

    assert response.status_code == 401
    assert b"get_user" not in response.body


@pytest.mark.asyncio
async def test_remote_action_manifest_lists_only_cli_actions() -> None:
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

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
    seen: list[Request] = []

    async def cli_auth(ctx: Request) -> AuthContext | None:
        seen.append(ctx)
        if ctx.headers.get("authorization") == "Bearer cli":
            return AuthContext(subject="cli-user")
        return None

    app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

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
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

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
@pytest.mark.parametrize(
    "rpc_body",
    [b"not valid json", b"[1, 2, 3]"],
    ids=["malformed-json", "non-mapping"],
)
async def test_remote_action_rpc_authenticates_even_when_action_name_is_unreadable(
    rpc_body: bytes,
) -> None:
    calls = 0
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

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
            body=rpc_body,
        )
    )

    # The action name can't be read, so the cli surface authenticator still runs
    # and denies before the handler — a malformed body must not bypass auth.
    assert response.status_code == 401
    assert calls == 0


@pytest.mark.asyncio
async def test_remote_action_rpc_auth_sees_cli_http_context() -> None:
    seen: list[Request] = []

    async def cli_auth(ctx: Request) -> AuthContext | None:
        seen.append(ctx)
        if ctx.headers.get("authorization") == "Bearer cli":
            return AuthContext(subject="cli-user")
        return None

    app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

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
    # Remote CLI now reaches MCP parity: auth sees the action name before binding.
    assert seen[0].context.action_name == "get_user"


@pytest.mark.asyncio
async def test_remote_action_does_not_leak_transport_headers_or_cookies() -> None:
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.get("/orders", cli=True, description="Read one order.")
    async def get_order(
        authorization: str | None = Header(default=None),
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
        session_id: str | None = Cookie(default=None, alias="session"),
    ) -> dict[str, object]:
        return {
            "authorization": authorization,
            "request_id": request_id,
            "session_id": session_id,
        }

    headers = {
        **authed_headers(),
        "cookie": "session=outer-cookie",
        "x-request-id": "outer-request",
    }
    status, body = await action_rpc(
        app,
        {"action": "get_order", "arguments": {}},
        headers=headers,
    )

    assert status == 200
    assert body["body"] == {
        "authorization": None,
        "request_id": None,
        "session_id": None,
    }


@pytest.mark.asyncio
async def test_remote_action_runs_global_middleware_once_on_real_handler() -> None:
    events: list[str] = []
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.before_request
    async def global_before(request: Request) -> Response | None:
        events.append(
            f"before:{request.path}:{request.context.source}:"
            f"{request.context.action_name}"
        )
        return None

    @app.after_response
    async def global_after(request: Request, response: Response) -> Response:
        events.append(f"after:{request.path}:{response.body.decode()}")
        return TextResponse("after saw handler response")

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    status, body = await action_rpc(
        app,
        {"action": "get_user", "arguments": {"id": 7}},
    )

    assert status == 200
    assert body == {
        "ok": True,
        "status_code": 200,
        "body": "after saw handler response",
    }
    assert events == [
        "before:/users/7:cli:get_user",
        'after:/users/7:{"id":7}',
    ]


@pytest.mark.asyncio
async def test_remote_action_uses_global_exception_handler_for_handler_errors() -> None:
    secret = "database password is secret"
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.exception_handler(RuntimeError)
    async def handle_runtime_error(
        request: Request,
        exc: Exception,
    ) -> Response | None:
        assert request.context.source == "cli"
        assert request.context.action_name == "danger"
        return TextResponse("mapped by global handler", status_code=418)

    @app.post("/danger", cli=True, description="Run dangerous action.")
    async def danger() -> dict[str, bool]:
        raise RuntimeError(secret)

    status, body = await action_rpc(app, {"action": "danger", "arguments": {}})

    assert status == 418
    assert body == {
        "ok": False,
        "status_code": 418,
        "body": "mapped by global handler",
    }
    assert secret not in json.dumps(body)


@pytest.mark.asyncio
async def test_remote_action_keeps_unhandled_global_middleware_errors_clean() -> None:
    secret = "middleware secret"
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.after_response
    async def broken_after(request: Request, response: Response) -> Response:
        raise RuntimeError(secret)

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    status, body = await action_rpc(
        app,
        {"action": "get_user", "arguments": {"id": 7}},
    )

    assert status == 500
    assert body["error"] == {"code": "action_failed", "message": "Action call failed"}
    assert secret not in json.dumps(body)


@pytest.mark.asyncio
async def test_remote_action_rpc_cannot_call_non_cli_route() -> None:
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

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

    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["cli"])], action_approval=approve
    )

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

    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["cli"])], action_approval=approve
    )

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

    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["cli"])], action_approval=approve
    )

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
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.post("/danger", cli=True, description="Run dangerous action.")
    async def danger() -> dict[str, bool]:
        raise RuntimeError("database password is secret")

    status, body = await action_rpc(app, {"action": "danger", "arguments": {}})

    assert status == 500
    assert body["error"] == {"code": "action_failed", "message": "Action call failed"}
    assert "secret" not in json.dumps(body)


@pytest.mark.asyncio
async def test_remote_action_rejects_oversized_response() -> None:
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

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
    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["cli"])], max_action_response_size=4
    )

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
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

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
    async def route_auth(ctx: Request) -> AuthContext | None:
        if ctx.headers.get("authorization") == "Bearer route":
            return AuthContext(subject="api-user")
        return None

    app = Quater(
        auth=[
            AuthConfig(route_auth, surfaces=["api"]),
            AuthConfig(authenticate, surfaces=["cli"]),
        ]
    )

    @app.get(
        "/private",
        cli=True,
        description="Read private data.",
    )
    async def private(request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {"subject": request.auth.subject}

    response = await app.handle(Request(method="GET", path="/private"))

    assert response.status_code == 401
    assert b"api-user" not in response.body
