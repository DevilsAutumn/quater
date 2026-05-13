from __future__ import annotations

import pytest

from quater import Quater, Request
from quater.cors import CORSConfig
from quater.exceptions import ConfigurationError
from quater.typing import AuthContext, AuthRequest


@pytest.mark.asyncio
async def test_allowed_origin_receives_cors_headers_and_vary_origin() -> None:
    app = Quater(
        cors=CORSConfig(
            allowed_origins=("https://app.example.com",),
            allow_credentials=True,
            expose_headers=("x-request-id",),
        )
    )

    @app.get("/items")
    async def items() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/items",
            headers={"origin": "https://app.example.com"},
        )
    )

    headers = dict(response.headers)
    assert headers["access-control-allow-origin"] == "https://app.example.com"
    assert headers["access-control-allow-credentials"] == "true"
    assert headers["access-control-expose-headers"] == "x-request-id"
    assert headers["vary"] == "Origin"


@pytest.mark.asyncio
async def test_disallowed_origin_does_not_receive_cors_headers() -> None:
    app = Quater(cors=CORSConfig(allowed_origins=("https://app.example.com",)))

    @app.get("/items")
    async def items() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/items",
            headers={"origin": "https://evil.example.com"},
        )
    )

    assert "access-control-allow-origin" not in dict(response.headers)


@pytest.mark.asyncio
async def test_preflight_response_uses_configured_allowed_headers() -> None:
    app = Quater(
        cors=CORSConfig(
            allowed_origins=("https://app.example.com",),
            allowed_headers=("authorization",),
            max_age=600,
        )
    )

    @app.route("OPTIONS", "/items")
    async def options() -> None:
        return None

    response = await app.handle(
        Request(
            method="OPTIONS",
            path="/items",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization, x-client",
            },
        )
    )

    headers = dict(response.headers)
    assert response.status_code == 204
    assert "POST" in headers["access-control-allow-methods"]
    assert headers["access-control-allow-headers"] == "authorization"
    assert headers["access-control-max-age"] == "600"


@pytest.mark.asyncio
async def test_preflight_reflects_requested_headers_when_unconfigured() -> None:
    app = Quater(cors=CORSConfig(allowed_origins=("https://app.example.com",)))

    response = await app.handle(
        Request(
            method="OPTIONS",
            path="/items",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "Authorization, X-Client",
            },
        )
    )

    headers = dict(response.headers)
    assert response.status_code == 204
    assert headers["access-control-allow-headers"] == "authorization, x-client"


@pytest.mark.asyncio
async def test_preflight_omits_invalid_requested_headers() -> None:
    app = Quater(cors=CORSConfig(allowed_origins=("https://app.example.com",)))

    response = await app.handle(
        Request(
            method="OPTIONS",
            path="/items",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization, bad header",
            },
        )
    )

    assert response.status_code == 204
    assert "access-control-allow-headers" not in dict(response.headers)


@pytest.mark.asyncio
async def test_preflight_wildcard_allowed_headers_reflects_sanitized_request() -> None:
    app = Quater(
        cors=CORSConfig(
            allowed_origins=("https://app.example.com",),
            allowed_headers=("*",),
        )
    )

    response = await app.handle(
        Request(
            method="OPTIONS",
            path="/items",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "Authorization, X-Client",
            },
        )
    )

    headers = dict(response.headers)
    assert response.status_code == 204
    assert headers["access-control-allow-headers"] == "authorization, x-client"


@pytest.mark.asyncio
async def test_preflight_does_not_require_route_or_authentication() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(
        cors=CORSConfig(
            allowed_origins=("https://app.example.com",),
            allowed_headers=("authorization",),
        )
    )

    @app.post("/items", auth=authenticate)
    async def create_item() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(
            method="OPTIONS",
            path="/items",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization",
            },
        )
    )

    headers = dict(response.headers)
    assert response.status_code == 204
    assert headers["access-control-allow-origin"] == "https://app.example.com"
    assert "POST" in headers["access-control-allow-methods"]
    assert headers["access-control-allow-headers"] == "authorization"
    assert auth_calls == 0
    assert handler_calls == 0


def test_wildcard_origin_with_credentials_fails_configuration() -> None:
    with pytest.raises(ConfigurationError):
        CORSConfig(allowed_origins=("*",), allow_credentials=True)


@pytest.mark.parametrize(
    "headers",
    (
        ("",),
        ("bad header",),
        ("x-good", "bad\rname"),
        (":authority",),
    ),
)
def test_invalid_cors_allowed_headers_fail_configuration(
    headers: tuple[str, ...],
) -> None:
    with pytest.raises(ConfigurationError, match="allowed_headers"):
        CORSConfig(
            allowed_origins=("https://app.example.com",),
            allowed_headers=headers,
        )
