from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import pytest

from quater import Quater, Request
from quater.cors import CORSConfig
from quater.exceptions import ConfigurationError
from quater.typing import AuthContext


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

    async def authenticate(ctx: Request) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(
        cors=CORSConfig(
            allowed_origins=("https://app.example.com",),
            allowed_headers=("authorization",),
        )
    )

    @app.post("/items")
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


def test_cors_allowed_methods_are_normalized() -> None:
    config = CORSConfig(
        allowed_origins=("https://app.example.com",),
        allowed_methods=("get", " PATCH ", "propfind"),
    )

    assert config.allowed_methods == ("GET", "PATCH", "PROPFIND")


def test_cors_default_allowed_methods_include_head() -> None:
    config = CORSConfig(allowed_origins=("https://app.example.com",))

    assert "HEAD" in config.allowed_methods


@pytest.mark.parametrize(
    "kwargs",
    (
        {"allowed_origins": "https://app.example.com"},
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_methods": "POST",
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_headers": "authorization",
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "expose_headers": "x-request-id",
        },
    ),
)
def test_cors_string_collection_fields_fail_early(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(
        ConfigurationError,
        match="must be an iterable of strings, not a single string",
    ):
        CORSConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    (
        {"allowed_origins": cast(tuple[str, ...], b"https://app.example.com")},
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_methods": cast(tuple[str, ...], b"POST"),
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_headers": cast(tuple[str, ...], bytearray(b"authorization")),
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "expose_headers": cast(tuple[str, ...], b"x-request-id"),
        },
    ),
)
def test_cors_bytes_collection_fields_fail_early(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ConfigurationError, match="must contain strings, not bytes"):
        CORSConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    (
        {"allowed_origins": cast(Iterable[str], {"https://app.example.com": "yes"})},
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_methods": cast(Iterable[str], {"POST": "yes"}),
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_headers": cast(Iterable[str], {"authorization": "yes"}),
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "expose_headers": cast(Iterable[str], {"x-request-id": "yes"}),
        },
    ),
)
def test_cors_mapping_collection_fields_fail_early(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ConfigurationError, match="must be an iterable of strings"):
        CORSConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    (
        {"allowed_origins": 123},
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_methods": 123,
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_headers": 123,
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "expose_headers": 123,
        },
    ),
)
def test_cors_non_iterable_collection_fields_fail_early(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ConfigurationError, match="must be an iterable of strings"):
        CORSConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    (
        {"allowed_origins": [cast(str, 123)]},
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_methods": [cast(str, 123)],
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "allowed_headers": [cast(str, 123)],
        },
        {
            "allowed_origins": ("https://app.example.com",),
            "expose_headers": [cast(str, 123)],
        },
    ),
)
def test_cors_non_string_collection_items_fail_early(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ConfigurationError, match="must contain only strings"):
        CORSConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "methods",
    (
        ("",),
        ("GET POST",),
        ("GET,POST",),
        ("GET\nX-Bad: yes",),
        ("GET\r\nX-Bad: yes",),
        ("GET/POST",),
        ("GÉT",),
    ),
)
def test_invalid_cors_allowed_methods_fail_configuration(
    methods: tuple[str, ...],
) -> None:
    with pytest.raises(ConfigurationError, match="allowed_methods"):
        CORSConfig(
            allowed_origins=("https://app.example.com",),
            allowed_methods=methods,
        )


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
