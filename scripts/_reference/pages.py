"""Reference page definitions and public-API validation."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _reference.paths import PACKAGE_INIT, REFERENCE_DIR
from _reference.signatures import object_for

MIN_PUBLIC_DOCSTRING_WORDS = 8
PLACEHOLDER_DOCSTRING_WORDS = frozenset({"todo", "tbd", "fixme", "placeholder"})


@dataclass(frozen=True, slots=True)
class ReferencePage:
    slug: str
    title: str
    description: str
    symbols: tuple[str, ...]

    @property
    def path(self) -> Path:
        return REFERENCE_DIR / f"{self.slug}.md"


PAGES: tuple[ReferencePage, ...] = (
    ReferencePage(
        slug="application",
        title="Application",
        description="App objects, route groups, and configuration.",
        symbols=("Quater", "RouteGroup", "AppConfig", "CORSConfig", "__version__"),
    ),
    ReferencePage(
        slug="resources",
        title="Resources",
        description="Request-scoped resources injected into handlers.",
        symbols=("Resource",),
    ),
    ReferencePage(
        slug="request",
        title="Request",
        description="Request data and state passed through handlers.",
        symbols=("Request", "State", "FormData", "UploadFile"),
    ),
    ReferencePage(
        slug="parameters",
        title="Parameters",
        description="Handler parameter markers for request data binding.",
        symbols=("Path", "Query", "Body", "Form", "File", "Header", "Cookie"),
    ),
    ReferencePage(
        slug="responses",
        title="Responses",
        description="Return values and explicit response classes.",
        symbols=(
            "Response",
            "JSONResponse",
            "TextResponse",
            "HTMLResponse",
            "BytesResponse",
            "StreamResponse",
            "RedirectResponse",
            "EmptyResponse",
        ),
    ),
    ReferencePage(
        slug="auth",
        title="Auth and Security",
        description=(
            "Auth hooks, approval hooks, framework errors, and signed cookies."
        ),
        symbols=(
            "AuthConfig",
            "AuthContext",
            "ApprovalRequest",
            "ActionApproval",
            "HTTPError",
            "ImproperlyConfigured",
            "SignedCookieSigner",
        ),
    ),
    ReferencePage(
        slug="observability",
        title="Observability",
        description="Access-log and MCP audit event types.",
        symbols=("AccessLogEvent", "AccessLogHook", "ToolAuditEvent"),
    ),
    ReferencePage(
        slug="testing",
        title="Testing",
        description="In-process HTTP, MCP, and CLI test clients.",
        symbols=("TestClient", "TestResponse", "MCPTestClient", "CliTestClient"),
    ),
)


def page_symbols(slug: str) -> tuple[str, ...]:
    for page in PAGES:
        if page.slug == slug:
            return page.symbols
    raise KeyError(slug)


def page_map(pages: Iterable[ReferencePage]) -> dict[str, ReferencePage]:
    mapped: dict[str, ReferencePage] = {}
    for page in pages:
        for symbol in page.symbols:
            if symbol in mapped:
                raise SystemExit(f"Duplicate reference symbol: {symbol}")
            mapped[symbol] = page
    return mapped


def read_public_api() -> tuple[str, ...]:
    module = ast.parse(PACKAGE_INIT.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise SystemExit("__all__ must be a list of strings")
        return tuple(value)
    raise SystemExit("Could not find quater.__all__")


def validate_public_docstrings(package: Any, public_api: tuple[str, ...]) -> None:
    missing: list[str] = []
    for name in public_api:
        obj = object_for(package, name)
        kind_name = str(getattr(obj, "kind", ""))
        if not kind_name.endswith(("CLASS", "FUNCTION")):
            continue
        docstring = getattr(obj, "docstring", None)
        value = getattr(docstring, "value", None)
        if not meaningful_docstring(value):
            missing.append(name)

    if missing:
        raise SystemExit(
            "Public classes/functions need meaningful docstrings: "
            + ", ".join(sorted(missing))
        )


def meaningful_docstring(value: object) -> bool:
    if not isinstance(value, str):
        return False
    words = re.findall(r"[A-Za-z0-9_]+", value)
    if len(words) < MIN_PUBLIC_DOCSTRING_WORDS:
        return False
    lowered = {word.lower() for word in words}
    return not bool(lowered & PLACEHOLDER_DOCSTRING_WORDS)
