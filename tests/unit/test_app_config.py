from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from quater import Quater
from quater.config import AppConfig
from quater.exceptions import ConfigurationError, RouteConflictError
from quater.request import Request
from quater.response import Response
from quater.typing import AuthContext, AuthRequest


async def allow_mcp_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="mcp")


def test_app_config_copies_mutable_inputs() -> None:
    allowed_hosts = ["api.example.com"]
    app = Quater(allowed_hosts=allowed_hosts, trusted_proxies=["127.0.0.1"])

    allowed_hosts.append("evil.example.com")

    assert app.config.allowed_hosts == ("api.example.com",)
    assert app.config.trusted_proxies == ("127.0.0.1",)


def test_app_config_is_immutable_after_creation() -> None:
    app = Quater(debug=True)
    field_name = "debug"

    with pytest.raises(FrozenInstanceError):
        setattr(app.config, field_name, False)

    assert app.config.debug is True


def test_app_config_overrides_do_not_mutate_base_config() -> None:
    base = AppConfig(allowed_hosts=("api.example.com",))
    app = Quater(config=base, allowed_hosts=["admin.example.com"], max_body_size="2mb")

    assert base.allowed_hosts == ("api.example.com",)
    assert base.max_body_size == 2 * 1024 * 1024
    assert app.config.allowed_hosts == ("admin.example.com",)
    assert app.config.max_body_size == 2 * 1024 * 1024


def test_secure_defaults_are_represented_in_config() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    assert app.config.debug is False
    assert app.config.security == "strict"
    assert app.config.allowed_hosts == ()
    assert app.config.trusted_proxies == ()
    assert app.config.max_body_size == 2 * 1024 * 1024
    assert app.config.max_form_parts == 1000
    assert app.config.max_form_field_size == 1024 * 1024
    assert app.config.max_file_size == 2 * 1024 * 1024
    assert app.config.upload_spool_size == 1024 * 1024
    assert app.config.max_tool_response_size == 1024 * 1024
    assert app.config.max_action_response_size == 1024 * 1024
    assert app.config.cors is None
    assert app.config.content_security_policy is None
    assert app.config.docs_path == "/docs"
    assert app.config.openapi_path == "/openapi.json"
    assert app.config.mcp_docs_path == "/mcp/docs"
    assert app.config.mcp_allowed_origins == ()
    assert app.config.request_id_header == "x-request-id"


def test_validate_production_accepts_safe_app() -> None:
    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.validate_production()


@pytest.mark.parametrize(
    ("app", "message"),
    (
        (
            Quater(debug=True, allowed_hosts=["api.example.com"]),
            "debug must be disabled",
        ),
        (Quater(), "allowed_hosts must be configured"),
        (Quater(allowed_hosts=["*"]), "allowed_hosts must not contain '*'"),
        (
            Quater(security="off", allowed_hosts=["api.example.com"]),
            "security must be 'strict'",
        ),
    ),
)
def test_validate_production_rejects_unsafe_config(
    app: Quater,
    message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        app.validate_production()


def test_validate_production_compiles_routes_first() -> None:
    app = Quater(allowed_hosts=["api.example.com"])

    @app.get("/users/{identifier}")
    async def by_identifier(identifier: str) -> dict[str, str]:
        return {"identifier": identifier}

    @app.get("/users/{name}")
    async def by_name(name: str) -> dict[str, str]:
        return {"name": name}

    with pytest.raises(RouteConflictError):
        app.validate_production()


def test_quater_reads_limit_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUATER_MAX_BODY_SIZE", "4mb")
    monkeypatch.setenv("QUATER_MAX_FORM_PARTS", "25")
    monkeypatch.setenv("QUATER_MAX_FORM_FIELD_SIZE", "64kb")
    monkeypatch.setenv("QUATER_MAX_FILE_SIZE", "8mb")
    monkeypatch.setenv("QUATER_UPLOAD_SPOOL_SIZE", "512kb")
    monkeypatch.setenv("QUATER_MAX_TOOL_RESPONSE_SIZE", "2mb")
    monkeypatch.setenv("QUATER_MAX_ACTION_RESPONSE_SIZE", "3mb")

    app = Quater()

    assert app.config.max_body_size == 4 * 1024 * 1024
    assert app.config.max_form_parts == 25
    assert app.config.max_form_field_size == 64 * 1024
    assert app.config.max_file_size == 8 * 1024 * 1024
    assert app.config.upload_spool_size == 512 * 1024
    assert app.config.max_tool_response_size == 2 * 1024 * 1024
    assert app.config.max_action_response_size == 3 * 1024 * 1024


def test_explicit_limit_options_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUATER_MAX_BODY_SIZE", "4mb")
    monkeypatch.setenv("QUATER_MAX_FILE_SIZE", "8mb")

    app = Quater(max_body_size="1mb", max_file_size="16kb")

    assert app.config.max_body_size == 1024 * 1024
    assert app.config.max_file_size == 16 * 1024


def test_explicit_config_does_not_read_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUATER_MAX_BODY_SIZE", "4mb")

    app = Quater(config=AppConfig(max_body_size=128))

    assert app.config.max_body_size == 128


@pytest.mark.parametrize(
    ("env_name", "value"),
    (
        ("QUATER_MAX_BODY_SIZE", "2tb"),
        ("QUATER_MAX_FORM_PARTS", "0"),
        ("QUATER_MAX_FORM_FIELD_SIZE", "-1mb"),
        ("QUATER_MAX_FILE_SIZE", ""),
    ),
)
def test_invalid_environment_limit_settings_fail_early(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(env_name, value)

    with pytest.raises(ConfigurationError, match=env_name):
        Quater()


@pytest.mark.parametrize("value", ["", "2", "mb", "2tb", "-1mb"])
def test_invalid_body_size_strings_fail_early(value: str) -> None:
    with pytest.raises(ConfigurationError):
        Quater(max_body_size=value)


@pytest.mark.parametrize(
    ("field_name", "path"),
    (
        ("docs_path", "/docs?debug=true"),
        ("openapi_path", "openapi.json"),
        ("mcp_docs_path", "/mcp/docs#tools"),
    ),
)
def test_invalid_documentation_paths_fail_early(
    field_name: str,
    path: str,
) -> None:
    with pytest.raises(ConfigurationError, match=field_name):
        if field_name == "docs_path":
            Quater(docs_path=path)
        elif field_name == "openapi_path":
            Quater(openapi_path=path)
        else:
            Quater(mcp_docs_path=path)


def test_docs_path_requires_openapi_path() -> None:
    with pytest.raises(ConfigurationError, match="docs_path requires openapi_path"):
        Quater(openapi_path=None)


def test_enabled_builtin_paths_must_be_distinct() -> None:
    with pytest.raises(ConfigurationError):
        Quater(docs_path="/mcp")

    with pytest.raises(ConfigurationError):
        Quater(docs_path="/openapi.json")

    with pytest.raises(ConfigurationError):
        Quater(mcp_docs_path="/mcp")


def test_trusted_proxies_must_be_ip_addresses_or_networks() -> None:
    with pytest.raises(ConfigurationError):
        Quater(trusted_proxies=["proxy.internal"])


def test_empty_content_security_policy_fails_early() -> None:
    with pytest.raises(ConfigurationError):
        Quater(content_security_policy=" ")


@pytest.mark.parametrize("header_name", ["", ":request-id", "bad header", "bad\rname"])
def test_invalid_request_id_header_fails_early(header_name: str) -> None:
    with pytest.raises(ConfigurationError, match="request_id_header"):
        Quater(request_id_header=header_name)


@pytest.mark.asyncio
async def test_unknown_request_returns_framework_response_object() -> None:
    response = await Quater().handle(Request(method="GET", path="/missing"))

    assert isinstance(response, Response)
    assert response.status_code == 404
    assert response.body == b"Not found: /missing"
    headers = dict(response.headers)
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert headers["x-content-type-options"] == "nosniff"


def test_route_metadata_can_be_registered_without_compiling_routes() -> None:
    async def handler() -> dict[str, bool]:
        return {"ok": True}

    app = Quater(mcp_auth=allow_mcp_auth)
    route = app.add_route(
        "get",
        "/health",
        handler,
        tool=True,
        description="Check health.",
    )

    assert app.routes == (route,)
    assert route.method == "GET"
    assert route.path == "/health"
    assert route.handler is handler
    assert route.name == "handler"
    assert route.description == "Check health."
    assert route.tool is True
    assert route.cli is False
    assert route.needs_approval is False
    assert route.auth is None
