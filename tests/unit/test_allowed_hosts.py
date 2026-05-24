from __future__ import annotations

import pytest

from quater import Quater, Request
from quater.typing import AuthContext, AuthRequest


@pytest.mark.asyncio
async def test_allowed_host_accepts_matching_host_with_port() -> None:
    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/health",
            headers={"host": "api.example.com:8443"},
        )
    )

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host",
    (
        "[api.example.com]",
        "[api.example.com]:443",
        "[api.example.com]evil.test",
        "[api.example.com]:bad",
        "[api.example.com]:",
    ),
)
async def test_allowed_host_rejects_malformed_bracketed_hosts(host: str) -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/private", auth=authenticate)
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/private", headers={"host": host})
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"
    assert auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ("[::1]", "[::1]:8443"))
async def test_allowed_host_accepts_bracketed_ipv6_hosts(host: str) -> None:
    app = Quater(allowed_hosts=["::1"])

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/health", headers={"host": host})
    )

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ("[localhost]", "[::1]."))
async def test_present_malformed_host_is_rejected_in_strict_default_mode(
    host: str,
) -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/health", headers={"host": host})
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host",
    (
        "localhost",
        "localhost:8000",
        "127.0.0.1",
        "127.0.0.1:8000",
        "[::1]:8000",
        "testserver",
    ),
)
async def test_strict_mode_defaults_to_local_allowed_hosts(host: str) -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/health", headers={"host": host})
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_strict_mode_default_rejects_non_local_hosts() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater()

    @app.get("/private", auth=authenticate)
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/private", headers={"host": "evil.example.com"})
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"
    assert auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_strict_mode_default_rejects_missing_host_from_network_client() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/health", client="203.0.113.10")
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"


@pytest.mark.asyncio
async def test_strict_mode_default_allows_missing_host_for_in_process_request() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/health"))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_relaxed_mode_without_allowed_hosts_keeps_allow_all_behavior() -> None:
    app = Quater(security="relaxed")

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/health", headers={"host": "api.example.com"})
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_wildcard_allowed_hosts_is_explicit_allow_all_at_runtime() -> None:
    app = Quater(allowed_hosts=["*"])

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/health", headers={"host": "api.example.com"})
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rejected_host_never_reaches_auth_or_handler() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/private", auth=authenticate)
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(method="GET", path="/private", headers={"host": "evil.example.com"})
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"
    assert auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_duplicate_host_header_is_rejected_before_auth_or_handler() -> None:
    auth_calls = 0
    handler_calls = 0

    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        nonlocal auth_calls
        auth_calls += 1
        return AuthContext(subject="user_1")

    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/private", auth=authenticate)
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/private",
            headers=(
                ("host", "api.example.com"),
                ("host", "evil.example.com"),
            ),
        )
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"
    assert auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_host_and_authority_must_agree() -> None:
    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(
        Request(
            method="GET",
            path="/health",
            headers=(
                ("host", "api.example.com"),
                (":authority", "evil.example.com"),
            ),
        )
    )

    assert response.status_code == 400
    assert response.body == b"Invalid Host header"


@pytest.mark.asyncio
async def test_forwarded_host_is_honored_only_from_trusted_proxy() -> None:
    app = Quater(
        allowed_hosts=["api.example.com"],
        trusted_proxies=["10.0.0.0/8"],
    )

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    trusted_response = await app.handle(
        Request(
            method="GET",
            path="/health",
            headers={"host": "internal", "x-forwarded-host": "api.example.com"},
            client="10.1.2.3",
        )
    )
    untrusted_response = await app.handle(
        Request(
            method="GET",
            path="/health",
            headers={"host": "internal", "x-forwarded-host": "api.example.com"},
            client="203.0.113.9",
        )
    )

    assert trusted_response.status_code == 200
    assert untrusted_response.status_code == 400
