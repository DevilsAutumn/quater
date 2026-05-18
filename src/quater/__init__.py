"""Public package surface for Quater."""

from quater._parameters import Body, Cookie, File, Form, Header, Path, Query
from quater._state import State
from quater.app import Quater
from quater.config import AppConfig
from quater.cookies import SignedCookieSigner
from quater.cors import CORSConfig
from quater.dependencies import Resource
from quater.exceptions import HTTPError, ImproperlyConfigured
from quater.formdata import FormData, UploadFile
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
]
