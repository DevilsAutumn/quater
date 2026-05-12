"""Public package surface for Quater."""

from quater.app import Quater
from quater.config import AppConfig
from quater.cookies import SignedCookieSigner
from quater.cors import CORSConfig
from quater.exceptions import HTTPError
from quater.groups import RouteGroup
from quater.observability import AccessLogEvent, AccessLogHook
from quater.request import Request
from quater.response import (
    BytesResponse,
    EmptyResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamResponse,
    TextResponse,
)
from quater.testing import MCPTestClient, TestClient, TestResponse
from quater.tools.audit import ToolAuditEvent
from quater.typing import ActionApproval, ApprovalRequest, AuthContext, AuthRequest

__version__ = "0.1.0a1"

__all__ = [
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
]
