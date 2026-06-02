from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import AuthConfig, AuthContext, HTTPError, Quater, Request, Resource


@pytest.mark.asyncio
async def test_auth_context_is_attached_before_handler_runs() -> None:
    async def authenticate(request: Request) -> AuthContext | None:
        return AuthContext(
            subject=request.headers["authorization"].removeprefix("Bearer "),
            metadata={"source": "test"},
        )

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/me")
    async def me(request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {
            "subject": request.auth.subject,
            "source": request.auth.metadata["source"],
        }

    response = await app.handle(
        Request(
            method="GET",
            path="/me",
            headers={"authorization": "Bearer user_123"},
        )
    )

    assert response.status_code == 200
    assert response.body == b'{"subject":"user_123","source":"test"}'


@pytest.mark.asyncio
async def test_missing_auth_context_denies_request_before_handler() -> None:
    handler_calls = 0

    async def authenticate(request: Request) -> AuthContext | None:
        return None

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/private"))

    assert response.status_code == 401
    assert response.body == b"Unauthorized"
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_auth_runs_even_when_request_auth_is_already_set() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(request: Request) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return None

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/private",
            auth=AuthContext(subject="preset"),
        )
    )

    assert response.status_code == 401
    assert response.body == b"Unauthorized"
    assert auth_calls == 1
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_auth_errors_do_not_leak_authorization_values() -> None:
    secret_token = "secret-token"

    async def authenticate(request: Request) -> AuthContext | None:
        raise RuntimeError(f"failed to verify {request.headers['authorization']}")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/private",
            headers={"authorization": secret_token},
        )
    )

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"
    assert secret_token.encode() not in response.body


@pytest.mark.asyncio
async def test_auth_resource_sees_auth_error_and_preserves_primary_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "session"
        except HTTPError:
            events.append("rollback")
            raise RuntimeError("rollback failed") from None
        finally:
            events.append("close")

    resource = Resource(provider)
    caplog.set_level("ERROR", logger="quater.finalize")

    async def authenticate(request: Request) -> AuthContext:
        await request.resolve(resource)
        raise HTTPError("Unauthorized", status_code=401)

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/private"))

    assert response.status_code == 401
    assert response.body == b"Unauthorized"
    assert events == ["open", "rollback", "close"]
    assert "Resource cleanup failed" in caplog.text
    assert "rollback failed" in caplog.text


@pytest.mark.asyncio
async def test_auth_resource_sees_later_handler_error() -> None:
    events: list[str] = []

    async def provider() -> AsyncIterator[str]:
        events.append("open")
        try:
            yield "session"
        except RuntimeError as exc:
            events.append(f"rollback:{exc}")
            raise
        else:
            events.append("commit")
        finally:
            events.append("close")

    resource = Resource(provider)

    async def authenticate(request: Request) -> AuthContext:
        await request.resolve(resource)
        return AuthContext(subject="user_1")

    app = Quater(debug=True, auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        raise RuntimeError("handler failed")

    response = await app.handle(Request(method="GET", path="/private"))

    assert response.status_code == 500
    assert response.body == b"RuntimeError: handler failed"
    assert events == ["open", "rollback:handler failed", "close"]


@pytest.mark.asyncio
async def test_auth_headers_are_read_only() -> None:
    seen_mutation_error = False

    async def authenticate(request: Request) -> AuthContext | None:
        nonlocal seen_mutation_error
        try:
            request.headers["authorization"] = "changed"  # type: ignore[index]
        except TypeError:
            seen_mutation_error = True
        return AuthContext(subject=request.headers["authorization"])

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/me")
    async def me(request: Request) -> dict[str, str]:
        assert request.auth is not None
        return {"subject": request.auth.subject}

    response = await app.handle(
        Request(method="GET", path="/me", headers={"authorization": "user_1"})
    )

    assert response.status_code == 200
    assert seen_mutation_error is True
    assert response.body == b'{"subject":"user_1"}'


@pytest.mark.asyncio
async def test_routes_without_an_auth_surface_stay_public() -> None:
    app = Quater()

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        return {"ok": True, "auth": request.auth is not None}

    response = await app.handle(Request(method="GET", path="/health"))

    assert response.status_code == 200
    assert response.body == b'{"ok":true,"auth":false}'


@pytest.mark.asyncio
async def test_public_opt_out_skips_auth_while_protected_routes_run_it() -> None:
    auth_calls = 0

    async def authenticate(request: Request) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        token = request.headers.get("authorization")
        if token != "Bearer user_1":
            return None
        return AuthContext(subject="user_1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/public", public=True)
    async def public() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/private")
    async def private(request: Request) -> dict[str, str]:
        assert request.auth is not None
        return {"subject": request.auth.subject}

    public_response = await app.handle(Request(method="GET", path="/public"))
    denied_response = await app.handle(Request(method="GET", path="/private"))
    private_response = await app.handle(
        Request(
            method="GET",
            path="/private",
            headers={"authorization": "Bearer user_1"},
        )
    )

    assert public_response.status_code == 200
    assert public_response.body == b'{"ok":true}'
    assert denied_response.status_code == 401
    assert private_response.status_code == 200
    assert private_response.body == b'{"subject":"user_1"}'
    assert auth_calls == 2


@pytest.mark.asyncio
async def test_http_tool_route_is_not_gated_by_the_mcp_surface() -> None:
    async def authenticate(request: Request) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])])

    @app.get("/public-tool", tool=True, description="Read public tool status.")
    async def public_tool() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/public-tool"))

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'
