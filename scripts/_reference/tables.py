"""Table content constants and table-building / validation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from _reference.signatures import annotation, clean_type, object_for, resolve
from _reference.types import (
    is_private_member,
    table_text,
    type_cell,
    type_name_cell,
)

FIELD_DOCS: Mapping[str, Mapping[str, str]] = {
    "AppConfig": {
        "debug": "Return detailed error responses while developing.",
        "security": "`strict`, `relaxed`, or `off` security defaults.",
        "allowed_hosts": "Host names the app should accept.",
        "trusted_proxies": "Proxy IPs or CIDR ranges trusted for forwarded headers.",
        "max_body_size": "Maximum request body size in bytes.",
        "max_form_parts": "Maximum number of form fields and file parts.",
        "max_form_field_size": "Maximum size for one string form field.",
        "max_file_size": "Maximum size for one uploaded file.",
        "upload_spool_size": "Per-file size before upload data rolls to disk.",
        "max_tool_response_size": "Maximum MCP tool response body size.",
        "max_action_response_size": "Maximum CLI action response body size.",
        "cors": "Optional CORS policy.",
        "content_security_policy": "Optional Content-Security-Policy header value.",
        "docs_path": "Swagger UI path. Set to `None` to disable it.",
        "openapi_path": "OpenAPI JSON path. Set to `None` to disable it.",
        "mcp_docs_path": "Human-readable MCP docs path. Set to `None` to disable it.",
        "mcp_allowed_origins": (
            "Origins allowed to call the MCP endpoint from browsers."
        ),
        "request_id_header": "Header used for incoming and outgoing request ids.",
    },
    "CORSConfig": {
        "allowed_origins": "Origins allowed to read browser responses.",
        "allowed_methods": "Methods allowed during browser preflight checks.",
        "allowed_headers": (
            "Request headers allowed during preflight. Empty reflects sanitized "
            "requested headers."
        ),
        "expose_headers": "Response headers browsers may expose to client code.",
        "allow_credentials": "Whether browsers may include credentials.",
        "max_age": "How long browsers may cache a preflight result.",
    },
    "AuthConfig": {
        "authenticator": "Async callable invoked for requests on covered surfaces.",
        "surfaces": (
            "Surfaces this authenticator covers (`api`, `mcp`, and/or `cli`)."
        ),
        "name": "Optional display name used in error and log messages.",
    },
    "AuthContext": {
        "subject": "Stable id for the authenticated user, service, or agent.",
        "metadata": "Small extra values your app wants to carry with the request.",
        "payload": (
            "App object the authenticator loaded (e.g. a `User` row) so handlers "
            "can read it back through a typed resource without a second lookup."
        ),
    },
    "ApprovalRequest": {
        "action": "Tool or CLI action name.",
        "arguments_hash": "Hash of the action name and canonical bound arguments.",
        "token": "Approval token supplied by the caller.",
        "auth": "Authenticated subject, when the action request was authenticated.",
        "context": "Quater context for the tool or CLI call.",
    },
    "AccessLogEvent": {
        "request_id": "Request id used for correlation.",
        "method": "HTTP method handled by Quater.",
        "path": "Path handled by Quater.",
        "status_code": "Final response status code.",
        "duration_ms": "Time spent handling the request.",
        "source": "`api`, `mcp`, or `cli`.",
        "entrypoint": "`server` for hosted calls, `local` for local CLI.",
        "scheme": "Request scheme.",
        "client": "Client address when available.",
        "tool_name": "MCP tool name when the request came from a tool call.",
        "action_name": "CLI action name when the request came from an action call.",
    },
    "ToolAuditEvent": {
        "tool_name": "MCP tool that was called.",
        "subject": "Authenticated subject, when present.",
        "success": "Whether the tool call completed successfully.",
        "duration_ms": "Tool call duration.",
        "arguments": "Redacted argument map passed to the audit hook.",
    },
}

REQUEST_CONSTRUCTOR_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("method", "str", "HTTP method used to create the normalized request."),
    ("path", "str", "Request path without the query string."),
    ("scheme", "str", "`http` or `https`. Defaults to `http`."),
    (
        "headers",
        "HeaderItems | Mapping[str, str]",
        "Incoming request headers. Exposed later as `request.headers`.",
    ),
    (
        "query_string",
        "str | bytes",
        "Raw query string. Exposed later as parsed `request.query`.",
    ),
    ("body", "RequestBody", "Raw bytes, async body reader, or `None`."),
    (
        "auth",
        "AuthContext | None",
        "Initial auth context. Most apps let route auth set this.",
    ),
    ("client", "str | None", "Client address when available."),
    (
        "context",
        "RequestContext | None",
        "Call-source context. Quater creates a default when omitted.",
    ),
    (
        "app",
        "Quater | None",
        "Application handling the request. Quater sets this at the app boundary.",
    ),
    ("max_body_size", "int | None", "Optional body-size limit for this request."),
    ("max_form_parts", "int | None", "Optional form part count limit."),
    (
        "max_form_field_size",
        "int | None",
        "Optional per-field form size limit.",
    ),
    ("max_file_size", "int | None", "Optional per-file upload size limit."),
    ("upload_spool_size", "int | None", "Optional upload spool threshold."),
)

RESPONSE_DOCS: Mapping[str, str] = {
    "Response": "Use this when you already have bytes and want full control.",
    "JSONResponse": "Use this when you need explicit status or headers for JSON.",
    "TextResponse": "Use this for plain text.",
    "HTMLResponse": "Use this for HTML.",
    "BytesResponse": "Use this for raw bytes.",
    "StreamResponse": "Use this for async byte streams.",
    "RedirectResponse": "Use this for redirects.",
    "EmptyResponse": "Use this for responses with no body.",
}

PARAMETER_DOCS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "Path": (
        "Bind a value from a route path segment.",
        (
            "`Path` is useful when the Python parameter name differs from the",
            "name in the route path, or when you want descriptions in OpenAPI",
            "and action schemas.",
        ),
    ),
    "Query": (
        "Bind a value from the query string.",
        (
            "`Query` makes query parameters explicit and lets you set aliases,",
            "defaults, and descriptions without changing handler logic.",
        ),
    ),
    "Body": (
        "Bind the JSON request body.",
        (
            "`Body` documents the body parameter and feeds the same schema into",
            "OpenAPI, MCP tools, and CLI actions.",
        ),
    ),
    "Form": (
        "Bind a scalar field from a submitted form.",
        (
            "`Form` reads fields from `application/x-www-form-urlencoded` or",
            "`multipart/form-data` requests. It is useful for browser forms,",
            "OAuth-style token endpoints, and compatibility with existing clients.",
        ),
    ),
    "File": (
        "Bind uploaded files from multipart form data.",
        (
            "`File` reads uploaded files from `multipart/form-data`. HTTP routes",
            "can receive files, but MCP tools and CLI actions cannot expose file",
            "parameters in this release.",
        ),
    ),
    "Header": (
        "Bind a value from an HTTP request header.",
        (
            "`Header` reads case-insensitive HTTP headers. When no alias is",
            "provided, underscores in the Python parameter name become hyphens.",
        ),
    ),
    "Cookie": (
        "Bind a value from a request cookie.",
        (
            "`Cookie` reads the parsed `Cookie` header and passes the selected",
            "cookie value to the handler.",
        ),
    ),
}

PARAMETER_OPTIONS: Mapping[str, tuple[tuple[str, str, str], ...]] = {
    "Path": (
        ("default", "object", "Path parameters are always required. Leave unset."),
        ("alias", "str | None", "Route path variable name when it differs."),
        ("description", "str | None", "Human description used in generated schemas."),
    ),
    "Query": (
        ("default", "object", "Default value. Omit it to make the parameter required."),
        ("alias", "str | None", "Query-string name when it differs."),
        ("description", "str | None", "Human description used in generated schemas."),
    ),
    "Body": (
        ("default", "object", "Default body value. Omit it to make the body required."),
        (
            "alias",
            "str | None",
            "MCP and CLI argument name. HTTP still reads the full body.",
        ),
        ("description", "str | None", "Human description used in generated schemas."),
    ),
    "Form": (
        ("default", "object", "Default value. Omit it to make the field required."),
        ("alias", "str | None", "Form field name when it differs."),
        ("description", "str | None", "Human description used in generated schemas."),
    ),
    "File": (
        ("default", "object", "Default value. Omit it to make the file required."),
        ("alias", "str | None", "Multipart field name when it differs."),
        ("description", "str | None", "Human description used in generated schemas."),
    ),
    "Header": (
        ("default", "object", "Default value. Omit it to make the header required."),
        ("alias", "str | None", "HTTP header name, such as `X-Request-ID`."),
        ("description", "str | None", "Human description used in generated schemas."),
        (
            "convert_underscores",
            "bool",
            "Convert `user_agent` to `user-agent` when no alias is set.",
        ),
    ),
    "Cookie": (
        ("default", "object", "Default value. Omit it to make the cookie required."),
        ("alias", "str | None", "Cookie name when it differs."),
        ("description", "str | None", "Human description used in generated schemas."),
    ),
}

QUATER_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("name", "str | None", "Optional app name used by generated metadata."),
    (
        "config",
        "AppConfig | None",
        "Base [AppConfig](#symbol-appconfig) to start from.",
    ),
    ("debug", "bool | None", "Override `config.debug`. Use only while developing."),
    ("security", "SecurityMode | None", "Override the security mode."),
    ("allowed_hosts", "Iterable[str] | None", "Hosts accepted by host checks."),
    (
        "trusted_proxies",
        "Iterable[str] | None",
        "Proxy IPs trusted for forwarded headers.",
    ),
    ("max_body_size", "MaxBodySize | None", "Maximum request body size."),
    ("max_form_parts", "int | None", "Maximum form field and file count."),
    (
        "max_form_field_size",
        "MaxBodySize | None",
        "Maximum size for one string form field.",
    ),
    ("max_file_size", "MaxBodySize | None", "Maximum size for one uploaded file."),
    (
        "upload_spool_size",
        "MaxBodySize | None",
        "Per-file size before upload data rolls to disk.",
    ),
    (
        "max_tool_response_size",
        "MaxBodySize | None",
        "Maximum MCP tool response body size.",
    ),
    (
        "max_action_response_size",
        "MaxBodySize | None",
        "Maximum CLI action response body size.",
    ),
    ("cors", "CORSConfig | None", "Optional [CORSConfig](#symbol-corsconfig)."),
    ("content_security_policy", "str | None", "Optional CSP response header."),
    ("mcp_docs_path", "str | None", "MCP docs path. `None` disables it."),
    ("mcp_allowed_origins", "Iterable[str] | None", "Browser origins allowed for MCP."),
    (
        "auth",
        "Iterable[AuthConfig] | None",
        "Per-surface [`AuthConfig`](./auth#symbol-authconfig) list. See "
        "[Auth](./auth).",
    ),
    (
        "mcp_audit",
        "AuditHook | None",
        "Receives redacted [MCP audit events](./observability#symbol-toolauditevent).",
    ),
    (
        "action_approval",
        "ActionApproval | None",
        "Required for protected tools/actions. See "
        "[ActionApproval](./auth#symbol-actionapproval).",
    ),
    (
        "access_logger",
        "AccessLogHook | None",
        "Receives "
        "[structured access log events](./observability#symbol-accesslogevent).",
    ),
    ("docs_path", "str | None", "Swagger UI path. `None` disables it."),
    ("openapi_path", "str | None", "OpenAPI JSON path. `None` disables it."),
    ("request_id_header", "str | None", "Correlation header name. `None` disables it."),
)

ROUTE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("method", "str", "HTTP method. Only passed to `route()` or `add_route()`."),
    ("path", "str", "Route path, such as `/orders/{order_id}`."),
    (
        "name",
        "str | None",
        "Operation name used in docs and exposed metadata. "
        "Defaults to the handler name.",
    ),
    (
        "description",
        "str | None",
        "Human text used by MCP tools, CLI actions, and docs.",
    ),
    ("tool", "bool", "Expose this route as an MCP tool."),
    ("cli", "bool", "Expose this route as a Quater CLI action."),
    ("needs_approval", "bool", "Require approval before MCP or CLI execution."),
    (
        "public",
        "PublicSurfaces",
        "Surfaces this route bypasses app-level auth on. `True` skips auth on "
        'every surface; an iterable of `"api"`/`"mcp"`/`"cli"` skips those '
        "surfaces only. See [Auth](./auth).",
    ),
    (
        "inject",
        "ResourceMap | None",
        "Handler resources created by Quater. See [Resources](/en/dev/resources).",
    ),
    (
        "metadata",
        "dict[str, Any] | None",
        "Extra metadata used by docs and extensions.",
    ),
    ("before", "Iterable[BeforeMiddleware]", "Route before-request middleware."),
    ("after", "Iterable[AfterMiddleware]", "Route after-response middleware."),
    ("around", "Iterable[AroundMiddleware]", "Route wrapper middleware."),
    (
        "exception_handlers",
        "Iterable[ExceptionHandlerEntry]",
        "Route-specific exception handlers.",
    ),
)

GROUP_ROUTE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("method", "str", "HTTP method. Only passed to `route()` or `add_route()`."),
    ("path", "str", "Group-relative route path, such as `/{order_id}`."),
    (
        "name",
        "str | None",
        "Operation name used in docs and exposed metadata. "
        "Defaults to the handler name.",
    ),
    (
        "description",
        "str | None",
        "Human text used by MCP tools, CLI actions, and docs.",
    ),
    ("tool", "bool", "Expose this route as an MCP tool."),
    ("cli", "bool", "Expose this route as a Quater CLI action."),
    ("needs_approval", "bool", "Require approval before MCP or CLI execution."),
    (
        "public",
        "PublicSurfaces",
        "Surfaces this route bypasses app-level auth on. See [Auth](./auth).",
    ),
    (
        "inject",
        "ResourceMap | None",
        "Handler resources created by Quater. See [Resources](/en/dev/resources).",
    ),
    (
        "metadata",
        "Mapping[str, Any] | None",
        "Extra metadata inherited into the final route.",
    ),
    ("before", "Iterable[BeforeMiddleware]", "Route before-request middleware."),
    ("after", "Iterable[AfterMiddleware]", "Route after-response middleware."),
    ("around", "Iterable[AroundMiddleware]", "Route wrapper middleware."),
    (
        "exception_handlers",
        "Iterable[ExceptionHandlerEntry]",
        "Route-specific exception handlers.",
    ),
)

ROUTE_GROUP_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("prefix", "str", "Path prefix applied to child routes."),
    ("tags", "Iterable[str]", "OpenAPI tags inherited by child routes."),
    (
        "inject",
        "ResourceMap | None",
        "Resources inherited by child routes. See [Resources](/en/dev/resources).",
    ),
    ("metadata", "Mapping[str, Any] | None", "Metadata inherited by child routes."),
    ("before", "Iterable[BeforeMiddleware]", "Before middleware inherited by routes."),
    ("after", "Iterable[AfterMiddleware]", "After middleware inherited by routes."),
    ("around", "Iterable[AroundMiddleware]", "Around middleware inherited by routes."),
    (
        "exception_handlers",
        "Iterable[ExceptionHandlerEntry]",
        "Exception handlers inherited by routes.",
    ),
)

RESPONSE_OPTIONS: Mapping[str, tuple[tuple[str, str, str], ...]] = {
    "Response": (
        ("body", "bytes", "Raw response body."),
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
        ("content_type", "str | None", "Sets `content-type` when not already set."),
    ),
    "JSONResponse": (
        ("content", "object", "Value serialized as JSON with msgspec."),
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
    ),
    "TextResponse": (
        ("content", "str", "Text encoded as UTF-8."),
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
        ("content_type", "str", "Text content type."),
    ),
    "HTMLResponse": (
        ("content", "str", "HTML encoded as UTF-8."),
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
    ),
    "BytesResponse": (
        ("content", "ResponseBody", "Bytes-like body value."),
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
        ("content_type", "str", "Byte response content type."),
    ),
    "StreamResponse": (
        ("body_iterator", "AsyncIterable[bytes]", "Async iterator yielding bytes."),
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
        ("content_type", "str", "Stream content type."),
    ),
    "RedirectResponse": (
        ("location", "str", "Redirect target."),
        ("status_code", "int", "Redirect status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
    ),
    "EmptyResponse": (
        ("status_code", "int", "HTTP status code."),
        ("headers", "HeaderItems | Mapping[str, str] | None", "Response headers."),
    ),
}

SET_COOKIE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("key", "str", "Cookie name. Must be a valid RFC 6265 token."),
    ("value", "str", "Cookie value. Must be a valid RFC 6265 cookie-octet string."),
    ("max_age", "int | None", "Max age in seconds."),
    ("expires", "int | None", "Expiry as a Unix timestamp."),
    ("path", "str | None", "Cookie path. Defaults to `/`."),
    ("domain", "str | None", "Cookie domain."),
    ("secure", "bool", "Set the `Secure` flag."),
    ("httponly", "bool", "Set the `HttpOnly` flag."),
    (
        "samesite",
        "Literal['lax', 'strict', 'none'] | None",
        'SameSite policy. `"none"` requires `secure=True`. Defaults to `"lax"`.',
    ),
)

DELETE_COOKIE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("key", "str", "Cookie name to delete."),
    ("path", "str | None", "Must match the path used when the cookie was set."),
    ("domain", "str | None", "Must match the domain used when the cookie was set."),
    ("secure", "bool", "Required for `__Secure-` and `__Host-` prefixed cookies."),
    ("httponly", "bool", "Set the `HttpOnly` flag."),
    (
        "samesite",
        "Literal['lax', 'strict', 'none'] | None",
        "Required when the deletion response is sent cross-site."
        ' `"none"` requires `secure=True`.',
    ),
)

HTTP_ERROR_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("detail", "str | None", "Error message returned to the client."),
    ("status_code", "int | None", "HTTP status code for the error response."),
)

SIGNED_COOKIE_SIGNER_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("secret", "SecretValue", "Current signing secret."),
    (
        "fallback_secrets",
        "Iterable[SecretValue]",
        "Old secrets accepted during rotation.",
    ),
    ("salt", "str", "Purpose-specific salt for cookie signatures."),
)

TEST_CLIENT_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("app", "object", "Quater app under test."),
    ("host", "str", "Host header used for requests."),
    ("scheme", "Literal['http', 'https']", "Request scheme."),
    ("client", "str", "Client address attached to requests."),
    ("headers", "HeaderItems | Mapping[str, str] | None", "Default headers."),
    ("cookies", "Mapping[str, str] | None", "Initial cookie jar."),
)

TEST_CLIENT_REQUEST_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("method", "str", "HTTP method."),
    ("path", "str", "Request path, optionally with a query string."),
    ("params", "QueryParams | None", "Extra query parameters."),
    ("headers", "HeaderItems | Mapping[str, str] | None", "Request headers."),
    ("cookies", "Mapping[str, str] | None", "Request cookies."),
    ("json", "object", "JSON body to encode."),
    ("content", "RequestContent | None", "Raw request body content."),
    (
        "data",
        "FormDataInput | None",
        "Form fields for URL-encoded or multipart requests.",
    ),
    ("files", "FilesInput | None", "Uploaded files for multipart requests."),
)

TEST_RESPONSE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("status_code", "int", "Response status code."),
    ("headers", "HeaderItems", "Collected response headers."),
    ("body", "bytes", "Collected response body."),
)

MCP_TEST_CLIENT_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("client", "TestClient", "HTTP test client used for MCP requests."),
)

MCP_TOOLS_CALL_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("name", "str", "Tool name to call."),
    ("arguments", "Mapping[str, object] | None", "Tool arguments."),
    ("request_id", "JSONRPCID", "JSON-RPC request id."),
    ("token", "str | None", "Bearer token used for MCP auth."),
    ("origin", "str | None", "Origin header used for MCP origin checks."),
    ("approval_token", "str | None", "Approval token for protected tools."),
    ("meta", "Mapping[str, object] | None", "Optional MCP `_meta` payload."),
    ("protocol_version", "str", "MCP protocol version header."),
    ("headers", "HeaderItems | Mapping[str, str] | None", "Extra request headers."),
)

CLI_TEST_CLIENT_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("client", "TestClient", "HTTP test client used for CLI action requests."),
)

CLI_CALL_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("action", "str", "Action name to call."),
    ("arguments", "Mapping[str, object] | None", "Action arguments."),
    ("token", "str | None", "Bearer token used for CLI auth."),
    (
        "dry_run",
        "bool",
        "Return the preflight payload instead of running the handler.",
    ),
    ("approval_token", "str | None", "Approval token for protected actions."),
    ("headers", "HeaderItems | Mapping[str, str] | None", "Extra request headers."),
)


def parameter_table(
    package: Any,
    symbol: str,
    method: str | None,
) -> tuple[tuple[str, str], ...]:
    obj = object_for(package, symbol)
    if method is None:
        member = getattr(obj, "members", {}).get("__init__")
    else:
        member = getattr(obj, "members", {}).get(method)
    if member is None:
        target = f"{symbol}.{method}" if method is not None else f"{symbol}.__init__"
        raise SystemExit(f"Could not find {target}")

    resolved = resolve(member)
    parameters = getattr(resolved, "parameters", ())
    rows: list[tuple[str, str]] = []
    for parameter in parameters:
        name = getattr(parameter, "name", "")
        if not name or name == "self":
            continue
        annotation_value = getattr(parameter, "annotation", None)
        type_name = "object" if annotation_value is None else str(annotation_value)
        rows.append((name, clean_type(type_name)))
    return tuple(rows)


def function_parameter_table(package: Any, symbol: str) -> tuple[tuple[str, str], ...]:
    obj = resolve(object_for(package, symbol))
    parameters = getattr(obj, "parameters", ())
    rows: list[tuple[str, str]] = []
    for parameter in parameters:
        name = getattr(parameter, "name", "")
        if not name:
            continue
        annotation_value = getattr(parameter, "annotation", None)
        type_name = "object" if annotation_value is None else str(annotation_value)
        rows.append((name, clean_type(type_name)))
    return tuple(rows)


def field_table(package: Any, symbol: str) -> list[str]:
    from _reference.signatures import init_annotations

    obj = object_for(package, symbol)
    annotations = init_annotations(obj)
    rows: list[str] = []
    actual_fields: set[str] = set()
    for name, member in getattr(obj, "members", {}).items():
        if is_private_member(name) or name in {"__slots__", "__test__"}:
            continue
        target = resolve(member)
        kind = str(getattr(target, "kind", ""))
        if not kind.endswith("ATTRIBUTE"):
            continue
        if "property" in getattr(target, "labels", set()):
            continue
        actual_fields.add(name)
        type_name = annotation(target)
        if type_name == "object":
            type_name = annotations.get(name, type_name)
        description = FIELD_DOCS.get(symbol, {}).get(name)
        if description is None:
            continue
        rows.append(
            f"| `{name}` | {type_cell(type_name)} | {table_text(description)} |"
        )

    documented_fields = set(FIELD_DOCS.get(symbol, {}))
    if actual_fields != documented_fields:
        missing = sorted(actual_fields - documented_fields)
        extra = sorted(documented_fields - actual_fields)
        raise SystemExit(
            f"{symbol} field docs mismatch; missing={missing}, extra={extra}"
        )

    if not rows:
        return []

    return [
        "Fields:",
        "",
        "| Field | Type | Meaning |",
        "| --- | --- | --- |",
        *rows,
        "",
    ]


def option_table(
    title: str,
    rows: Sequence[tuple[str, str, str]],
) -> list[str]:
    lines = [f"### {title}", "", "| Name | Type | Meaning |", "| --- | --- | --- |"]
    for name, type_name, description in rows:
        lines.append(
            f"| `{name}` | {type_cell(type_name)} | {table_text(description)} |"
        )
    lines.append("")
    return lines


def validated_option_table(
    package: Any,
    symbol: str,
    method: str | None,
    title: str,
    rows: Sequence[tuple[str, str, str]],
) -> list[str]:
    actual = parameter_table(package, symbol, method)
    expected = tuple((name, type_name) for name, type_name, _ in rows)
    if actual != expected:
        target = f"{symbol}.{method}" if method is not None else symbol
        raise SystemExit(
            f"{target} reference table mismatch; actual={actual}, expected={expected}"
        )
    return option_table(title, rows)


def validated_function_option_table(
    package: Any,
    symbol: str,
    title: str,
    rows: Sequence[tuple[str, str, str]],
) -> list[str]:
    actual = function_parameter_table(package, symbol)
    expected = tuple((name, type_name) for name, type_name, _ in rows)
    if actual != expected:
        raise SystemExit(
            f"{symbol} reference table mismatch; actual={actual}, expected={expected}"
        )
    return option_table(title, rows)


def type_section(rows: Sequence[tuple[str, str]]) -> list[str]:
    lines = ["## Type Names Used Here", "", "| Name | Meaning |", "| --- | --- |"]
    for name, description in rows:
        lines.append(f"| {type_name_cell(name)} | {table_text(description)} |")
    lines.append("")
    return lines
