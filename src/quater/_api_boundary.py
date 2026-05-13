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
    "BytesResponse",
    "CORSConfig",
    "EmptyResponse",
    "HTTPError",
    "HTMLResponse",
    "JSONResponse",
    "Quater",
    "RedirectResponse",
    "Request",
    "Response",
    "RouteGroup",
    "SignedCookieSigner",
    "StreamResponse",
    "MCPTestClient",
    "TestClient",
    "TestResponse",
    "TextResponse",
    "ToolAuditEvent",
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
        "docs",
        "groups",
        "lifespan",
        "middleware",
        "observability",
        "params",
        "protocol",
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
