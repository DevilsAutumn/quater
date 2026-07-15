"""Route definitions and handlers for built-in documentation."""

from __future__ import annotations

from typing import cast

from quater.config import AppConfig, docs_asset_paths
from quater.core import _AUTH_SURFACE_METADATA, Handler, RouteDefinition
from quater.docs.swagger import (
    ensure_swagger_ui_assets_available,
    swagger_ui_asset_response,
    swagger_ui_initializer_response,
)
from quater.response import Response


def build_builtin_docs_routes(
    config: AppConfig,
    *,
    openapi_json_handler: Handler,
    openapi_docs_handler: Handler,
    mcp_docs_handler: Handler,
) -> tuple[RouteDefinition, ...]:
    """Build the enabled OpenAPI, Swagger UI, and MCP docs routes."""

    routes: list[RouteDefinition] = []
    if config.openapi_path is not None:
        routes.append(
            RouteDefinition(
                method="GET",
                path=config.openapi_path,
                handler=openapi_json_handler,
                name="quater_openapi_json",
                metadata={"include_in_openapi": False},
            )
        )
    if config.docs_path is not None:
        openapi_path = cast(str, config.openapi_path)

        ensure_swagger_ui_assets_available()
        routes.append(
            RouteDefinition(
                method="GET",
                path=config.docs_path,
                handler=openapi_docs_handler,
                name="quater_openapi_docs",
                metadata={"include_in_openapi": False},
            )
        )
        asset_paths = docs_asset_paths(config.docs_path)
        for asset_name, handler in _swagger_ui_asset_handlers(openapi_path).items():
            routes.append(
                RouteDefinition(
                    method="GET",
                    path=asset_paths[asset_name],
                    handler=handler,
                    name=f"quater_docs_{asset_name.replace('-', '_')}",
                    metadata={"include_in_openapi": False},
                )
            )
    if config.mcp_docs_path is not None:
        routes.append(
            RouteDefinition(
                method="GET",
                path=config.mcp_docs_path,
                handler=mcp_docs_handler,
                name="quater_mcp_docs",
                metadata={
                    "include_in_openapi": False,
                    _AUTH_SURFACE_METADATA: "mcp",
                },
            )
        )
    return tuple(routes)


def _swagger_ui_asset_handlers(openapi_path: str) -> dict[str, Handler]:
    return {
        "swagger-ui.css": _swagger_ui_asset_handler("swagger-ui.css"),
        "swagger-ui-bundle.js": _swagger_ui_asset_handler("swagger-ui-bundle.js"),
        "swagger-ui-standalone-preset.js": _swagger_ui_asset_handler(
            "swagger-ui-standalone-preset.js"
        ),
        "swagger-initializer.js": _swagger_ui_initializer_handler(openapi_path),
        "favicon-32x32.png": _swagger_ui_asset_handler("favicon-32x32.png"),
    }


def _swagger_ui_asset_handler(asset_name: str) -> Handler:
    async def handler() -> Response:
        return swagger_ui_asset_response(asset_name)

    return handler


def _swagger_ui_initializer_handler(openapi_path: str) -> Handler:
    async def handler() -> Response:
        return swagger_ui_initializer_response(openapi_path)

    return handler
