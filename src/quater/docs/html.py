"""HTML rendering helpers for built-in documentation pages."""

from __future__ import annotations

from html import escape
from inspect import Signature
from typing import get_type_hints

from quater.config import join_path
from quater.core import RouteDefinition
from quater.request import Request
from quater.response import Response
from quater.schema import annotation_schema, strip_optional
from quater.serialization import dumps_pretty_json
from quater.tools.registry import ToolRegistry

DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


def render_openapi_docs(
    *,
    openapi_json_path: str,
    swagger_ui_base_path: str,
) -> str:
    favicon = _asset(swagger_ui_base_path, "favicon-32x32.png")
    stylesheet = _asset(swagger_ui_base_path, "swagger-ui.css")
    bundle_js = _asset(swagger_ui_base_path, "swagger-ui-bundle.js")
    preset_js = _asset(swagger_ui_base_path, "swagger-ui-standalone-preset.js")
    initializer_js = _asset(swagger_ui_base_path, "swagger-initializer.js")
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Quater API Docs</title>"
        f'<link rel="icon" href="{favicon}">'
        f'<link rel="stylesheet" href="{stylesheet}">'
        "</head>"
        "<body>"
        '<div id="swagger-ui"></div>'
        f'<script src="{bundle_js}"></script>'
        f'<script src="{preset_js}"></script>'
        f'<script src="{initializer_js}" '
        f'data-openapi-url="{escape(openapi_json_path, quote=True)}"></script>'
        "</body>"
        "</html>"
    )


def render_mcp_docs(
    registry: ToolRegistry,
    *,
    mcp_endpoint: str,
    mcp_protected: bool = False,
) -> str:
    tools = sorted(registry.tools.values(), key=lambda tool: tool.name)
    body_parts: list[str] = []
    for tool in tools:
        body_parts.append(
            _render_tool(
                tool,
                mcp_endpoint=mcp_endpoint,
                mcp_protected=mcp_protected,
            )
        )

    if not body_parts:
        body_parts.append('<p class="empty">No MCP tools are registered yet.</p>')

    return _page(
        title="MCP Tools",
        eyebrow="MCP",
        heading="MCP Tools",
        lead=(
            "Human-readable view of the same tool metadata returned by "
            "<code>tools/list</code>."
        ),
        body="\n".join(body_parts),
    )


def _render_tool(
    tool: object,
    *,
    mcp_endpoint: str,
    mcp_protected: bool,
) -> str:
    from quater.tools.registry import ToolDefinition

    if not isinstance(tool, ToolDefinition):
        return ""

    route = tool.route
    # A tool only requires auth when the mcp surface has an authenticator and the
    # route is not opted out as public. With no mcp AuthConfig every tool is
    # callable without authentication, so it is reported as public.
    requires_auth = mcp_protected and "mcp" not in route.public
    auth = "required" if requires_auth else "public"
    output_schema = _output_schema(route)
    output_block = (
        _schema_block("Output Schema", output_schema)
        if output_schema is not None
        else ""
    )
    example_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool.name,
            "arguments": _example_arguments(tool.input_schema),
        },
    }

    return (
        '<section class="operation">'
        f'<div class="route-line"><span class="method tool">TOOL</span>'
        f"<code>{escape(tool.name)}</code></div>"
        f"<h2>{escape(tool.name)}</h2>"
        f"<p>{escape(tool.description)}</p>"
        f'<p class="meta">Endpoint: <code>POST {escape(mcp_endpoint)}</code></p>'
        f'<p class="meta">HTTP route: <code>{escape(route.method)} '
        f"{escape(route.path)}</code></p>"
        f'<p class="meta">Auth: {auth}</p>'
        f"{_schema_block('Input Schema', tool.input_schema)}"
        f"{output_block}"
        f"{_schema_block('Example Request', example_request)}"
        "</section>"
    )


def _schema_block(title: str, value: object) -> str:
    return (
        f"<h3>{escape(title)}</h3><pre>{escape(_json_text(value), quote=False)}</pre>"
    )


def _output_schema(route: RouteDefinition) -> dict[str, object] | None:
    annotation = _return_annotation(route)
    if annotation is Signature.empty or annotation is None or annotation is type(None):
        return None

    stripped = strip_optional(annotation)
    if stripped is Request:
        return None
    if isinstance(stripped, type) and issubclass(stripped, Response):
        return None
    return annotation_schema(annotation)


def _return_annotation(route: RouteDefinition) -> object:
    try:
        return get_type_hints(route.handler).get("return", Signature.empty)
    except NameError:
        return route.handler.__annotations__.get("return", Signature.empty)


def _example_arguments(input_schema: dict[str, object]) -> dict[str, object]:
    properties = _object(input_schema.get("properties"))
    required = {
        item for item in _list(input_schema.get("required")) if isinstance(item, str)
    }
    return {
        name: _example_value(_object(schema))
        for name, schema in properties.items()
        if isinstance(name, str) and name in required
    }


def _example_value(schema: dict[object, object]) -> object:
    schema_type = schema.get("type")
    if schema_type == "integer":
        return 123
    if schema_type == "number":
        return 12.3
    if schema_type == "boolean":
        return True
    if schema_type == "array":
        return []
    if schema_type == "string":
        return "string"
    return {}


def _json_text(value: object) -> str:
    return dumps_pretty_json(value).decode("utf-8")


def _object(value: object) -> dict[object, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _asset(base_path: str, asset_name: str) -> str:
    return escape(join_path(base_path, asset_name), quote=True)


def _page(
    *,
    title: str,
    eyebrow: str,
    heading: str,
    lead: str,
    body: str,
) -> str:
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        "<style>"
        ":root{color-scheme:light dark;font-family:Inter,ui-sans-serif,system-ui,"
        "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;"
        "color:#111827}"
        "body{margin:0}"
        "main{max-width:1120px;margin:0 auto;padding:40px 20px 64px}"
        ".eyebrow{font-size:12px;font-weight:700;letter-spacing:.08em;"
        "text-transform:uppercase;color:#2563eb}"
        "h1{margin:8px 0 8px;font-size:38px;line-height:1.1}"
        "h2{margin:12px 0 8px;font-size:22px}"
        "h3{margin:18px 0 8px;font-size:14px;text-transform:uppercase;"
        "letter-spacing:.04em;color:#4b5563}"
        "p{line-height:1.6}"
        "a{color:#2563eb}"
        ".operation{margin-top:18px;border:1px solid #d1d5db;border-radius:8px;"
        "background:#fff;padding:20px}"
        ".route-line{display:flex;align-items:center;gap:10px;flex-wrap:wrap}"
        ".method{display:inline-flex;align-items:center;justify-content:center;"
        "min-width:62px;border-radius:6px;padding:5px 8px;font-size:12px;"
        "font-weight:800;color:white;background:#4b5563}"
        ".method.get{background:#059669}.method.post{background:#2563eb}"
        ".method.put{background:#7c3aed}.method.patch{background:#d97706}"
        ".method.delete{background:#dc2626}.method.tool{background:#ED4B2F}"
        "code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"
        "'Liberation Mono','Courier New',monospace}"
        "pre{overflow:auto;border-radius:8px;background:#111827;color:#f9fafb;"
        "padding:14px;font-size:13px;line-height:1.5}"
        "table{width:100%;border-collapse:collapse;margin-top:8px}"
        "th,td{text-align:left;border-bottom:1px solid #e5e7eb;padding:10px;"
        "vertical-align:top}"
        "th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;"
        "color:#4b5563}"
        ".meta,.empty{color:#4b5563}"
        "@media (prefers-color-scheme:dark){:root{background:#030712;"
        "color:#f9fafb}.operation{background:#111827;border-color:#374151}"
        "th,td{border-color:#374151}.meta,.empty,h3{color:#9ca3af}}"
        "</style>"
        "</head>"
        "<body>"
        "<main>"
        f'<div class="eyebrow">{escape(eyebrow)}</div>'
        f"<h1>{escape(heading)}</h1>"
        f"<p>{lead}</p>"
        f"{body}"
        "</main>"
        "</body>"
        "</html>"
    )
