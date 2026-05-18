"""Internal source of truth for Quater's import boundary."""

from __future__ import annotations

from typing import Final

PUBLIC_API_SYMBOLS: Final[tuple[str, ...]] = (
    "ActionApproval",
    "AccessLogEvent",
    "AccessLogHook",
    "AppConfig",
    "ApprovalRequest",
    "AuthContext",
    "AuthRequest",
    "Body",
    "BytesResponse",
    "CORSConfig",
    "Cookie",
    "EmptyResponse",
    "File",
    "Form",
    "FormData",
    "HTTPError",
    "Header",
    "HTMLResponse",
    "ImproperlyConfigured",
    "JSONResponse",
    "Path",
    "Quater",
    "Query",
    "RedirectResponse",
    "Request",
    "Response",
    "Resource",
    "RouteGroup",
    "SignedCookieSigner",
    "State",
    "StreamResponse",
    "MCPTestClient",
    "TestClient",
    "TestResponse",
    "TextResponse",
    "ToolAuditEvent",
    "UploadFile",
    "__version__",
)

PUBLIC_SUBMODULES: Final[frozenset[str]] = frozenset(
    {
        "adapters",
        "exceptions",
        "testing",
        "types",
        "typing",
    }
)

INTERNAL_SUBMODULES: Final[frozenset[str]] = frozenset(
    {
        "actions",
        "app",
        "auth",
        "cli",
        "config",
        "cookies",
        "core",
        "cors",
        "datastructures",
        "deployment",
        "dependencies",
        "docs",
        "groups",
        "formdata",
        "lifespan",
        "middleware",
        "observability",
        "protocol",
        "params",
        "request",
        "response",
        "router",
        "routing",
        "schema",
        "security",
        "serialization",
        "tools",
    }
)
