from __future__ import annotations

from typing import cast

import pytest

from quater import Quater
from quater.config import AppConfig
from quater.core import RouteDefinition
from quater.docs import routes as docs_routes
from quater.response import BytesResponse, EmptyResponse, Response


async def _openapi_json() -> Response:
    return EmptyResponse()


async def _openapi_docs() -> Response:
    return EmptyResponse()


async def _mcp_docs() -> Response:
    return EmptyResponse()


def _build_routes(config: AppConfig) -> tuple[RouteDefinition, ...]:
    return docs_routes.build_builtin_docs_routes(
        config,
        openapi_json_handler=_openapi_json,
        openapi_docs_handler=_openapi_docs,
        mcp_docs_handler=_mcp_docs,
    )


def test_default_builtin_docs_routes_keep_their_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docs_routes, "ensure_swagger_ui_assets_available", lambda: None)

    routes = docs_routes.build_builtin_docs_routes(
        AppConfig(),
        openapi_json_handler=_openapi_json,
        openapi_docs_handler=_openapi_docs,
        mcp_docs_handler=_mcp_docs,
    )

    assert [
        (route.method, route.path, route.name, route.metadata) for route in routes
    ] == [
        (
            "GET",
            "/openapi.json",
            "quater_openapi_json",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/docs",
            "quater_openapi_docs",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/docs/swagger-ui.css",
            "quater_docs_swagger_ui.css",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/docs/swagger-ui-bundle.js",
            "quater_docs_swagger_ui_bundle.js",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/docs/swagger-ui-standalone-preset.js",
            "quater_docs_swagger_ui_standalone_preset.js",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/docs/swagger-initializer.js",
            "quater_docs_swagger_initializer.js",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/docs/favicon-32x32.png",
            "quater_docs_favicon_32x32.png",
            {"include_in_openapi": False},
        ),
        (
            "GET",
            "/mcp/docs",
            "quater_mcp_docs",
            {
                "include_in_openapi": False,
                "quater_auth_surface": "mcp",
            },
        ),
    ]
    assert routes[0].handler is _openapi_json
    assert routes[1].handler is _openapi_docs
    assert routes[-1].handler is _mcp_docs


def test_quater_combines_docs_and_cli_builtin_routes_without_contract_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docs_routes, "ensure_swagger_ui_assets_available", lambda: None)
    app = Quater()

    @app.get("/health", cli=True, description="Check service health.")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    routes = app._builtin_routes()

    assert tuple(route.name for route in routes) == (
        "quater_openapi_json",
        "quater_openapi_docs",
        "quater_docs_swagger_ui.css",
        "quater_docs_swagger_ui_bundle.js",
        "quater_docs_swagger_ui_standalone_preset.js",
        "quater_docs_swagger_initializer.js",
        "quater_docs_favicon_32x32.png",
        "quater_mcp_docs",
        "quater_actions_manifest",
        "quater_actions_call",
    )
    assert routes[-2].metadata == {
        "include_in_openapi": False,
        "quater_builtin": "actions_manifest",
        "quater_auth_surface": "cli",
    }
    assert routes[-1].metadata == {
        "include_in_openapi": False,
        "quater_builtin": "actions_call",
        "quater_auth_surface": "cli",
        "quater_skip_global_middleware": True,
    }


@pytest.mark.parametrize(
    ("config", "expected_names"),
    [
        (
            AppConfig(docs_path=None),
            ("quater_openapi_json", "quater_mcp_docs"),
        ),
        (
            AppConfig(docs_path=None, openapi_path=None),
            ("quater_mcp_docs",),
        ),
        (
            AppConfig(docs_path=None, openapi_path=None, mcp_docs_path=None),
            (),
        ),
        (
            AppConfig(mcp_docs_path=None),
            (
                "quater_openapi_json",
                "quater_openapi_docs",
                "quater_docs_swagger_ui.css",
                "quater_docs_swagger_ui_bundle.js",
                "quater_docs_swagger_ui_standalone_preset.js",
                "quater_docs_swagger_initializer.js",
                "quater_docs_favicon_32x32.png",
            ),
        ),
    ],
)
def test_builtin_docs_routes_honor_enabled_surfaces(
    config: AppConfig,
    expected_names: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_checked() -> None:
        if config.docs_path is None:
            raise AssertionError("disabled Swagger UI must not check its asset bundle")

    monkeypatch.setattr(
        docs_routes,
        "ensure_swagger_ui_assets_available",
        fail_if_checked,
    )

    routes = _build_routes(config)

    assert tuple(route.name for route in routes) == expected_names


@pytest.mark.parametrize(
    ("docs_path", "expected_asset_path"),
    [
        ("/api-docs", "/api-docs/swagger-ui.css"),
        ("/api-docs/", "/api-docs/swagger-ui.css"),
        ("/", "/swagger-ui.css"),
    ],
)
def test_builtin_docs_routes_use_custom_and_root_docs_paths(
    docs_path: str,
    expected_asset_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docs_routes, "ensure_swagger_ui_assets_available", lambda: None)

    routes = _build_routes(
        AppConfig(
            docs_path=docs_path,
            openapi_path="/schema.json",
            mcp_docs_path=None,
        )
    )

    assert routes[1].path == docs_path
    assert routes[2].path == expected_asset_path


@pytest.mark.asyncio
async def test_swagger_asset_handlers_serve_every_asset_and_custom_initializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_calls: list[str] = []
    initializer_calls: list[str] = []

    def asset_response(asset_name: str) -> BytesResponse:
        asset_calls.append(asset_name)
        return BytesResponse(asset_name.encode())

    def initializer_response(openapi_path: str) -> BytesResponse:
        initializer_calls.append(openapi_path)
        return BytesResponse(openapi_path.encode())

    monkeypatch.setattr(docs_routes, "ensure_swagger_ui_assets_available", lambda: None)
    monkeypatch.setattr(docs_routes, "swagger_ui_asset_response", asset_response)
    monkeypatch.setattr(
        docs_routes,
        "swagger_ui_initializer_response",
        initializer_response,
    )
    routes = _build_routes(
        AppConfig(
            docs_path="/api-docs",
            openapi_path="/schema.json",
            mcp_docs_path=None,
        )
    )
    asset_routes = routes[2:]

    responses = [cast(BytesResponse, await route.handler()) for route in asset_routes]

    assert asset_calls == [
        "swagger-ui.css",
        "swagger-ui-bundle.js",
        "swagger-ui-standalone-preset.js",
        "favicon-32x32.png",
    ]
    assert initializer_calls == ["/schema.json"]
    assert [response.body for response in responses] == [
        b"swagger-ui.css",
        b"swagger-ui-bundle.js",
        b"swagger-ui-standalone-preset.js",
        b"/schema.json",
        b"favicon-32x32.png",
    ]


def test_enabled_swagger_ui_checks_the_asset_bundle_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def ensure_assets() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        docs_routes,
        "ensure_swagger_ui_assets_available",
        ensure_assets,
    )

    _build_routes(AppConfig())

    assert calls == 1
