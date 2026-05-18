from __future__ import annotations

import importlib
import importlib.resources
import json
import os
import pathlib
import pkgutil
import re
import subprocess
import sys

import quater
from quater import (
    AccessLogEvent,
    AccessLogHook,
    ActionApproval,
    AppConfig,
    ApprovalRequest,
    AuthContext,
    AuthRequest,
    Body,
    Cookie,
    CORSConfig,
    File,
    Form,
    FormData,
    Header,
    ImproperlyConfigured,
    MCPTestClient,
    Path,
    Quater,
    Query,
    Resource,
    RouteGroup,
    SignedCookieSigner,
    State,
    TestClient,
    TestResponse,
    ToolAuditEvent,
    UploadFile,
)
from quater._api_boundary import (
    INTERNAL_SUBMODULES,
    PUBLIC_API_SYMBOLS,
    PUBLIC_SUBMODULES,
)


def test_package_imports_from_outside_source_tree_without_optional_eager_imports(
    tmp_path: pathlib.Path,
) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    src_path = repo_root / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_path)

    script = """
import json
import os
import sys

os.chdir(sys.argv[1])
import quater

print(json.dumps({
    "file": quater.__file__,
    "has_quater": hasattr(quater, "Quater"),
        "has_app": hasattr(quater, "App"),
        "granian_eager": "granian" in sys.modules,
        "msgspec_eager": "msgspec" in sys.modules,
        "router_eager": "quater._router" in sys.modules,
    }))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["has_quater"] is True
    assert payload["has_app"] is False
    assert pathlib.Path(payload["file"]).is_relative_to(src_path)
    assert payload["granian_eager"] is False
    assert payload["msgspec_eager"] is False
    assert payload["router_eager"] is False


def test_public_exports_are_intentionally_small() -> None:
    assert quater.__all__ == list(PUBLIC_API_SYMBOLS)
    assert quater.Quater is Quater
    assert quater.RouteGroup is RouteGroup
    assert not hasattr(quater, "App")
    assert quater.ActionApproval is ActionApproval
    assert quater.AccessLogEvent is AccessLogEvent
    assert quater.AccessLogHook is AccessLogHook
    assert quater.ApprovalRequest is ApprovalRequest
    assert quater.AuthContext is AuthContext
    assert quater.AuthRequest is AuthRequest
    assert quater.Body is Body
    assert quater.Cookie is Cookie
    assert quater.File is File
    assert quater.Form is Form
    assert quater.FormData is FormData
    assert quater.Header is Header
    assert quater.Path is Path
    assert quater.Query is Query
    assert quater.Resource is Resource
    assert quater.AppConfig is AppConfig
    assert quater.CORSConfig is CORSConfig
    assert quater.ImproperlyConfigured is ImproperlyConfigured
    assert quater.SignedCookieSigner is SignedCookieSigner
    assert quater.State is State
    assert quater.MCPTestClient is MCPTestClient
    assert quater.TestClient is TestClient
    assert quater.TestResponse is TestResponse
    assert quater.ToolAuditEvent is ToolAuditEvent
    assert quater.UploadFile is UploadFile


def test_top_level_submodules_are_intentionally_classified() -> None:
    package_path = pathlib.Path(quater.__file__).parent
    discovered = {
        module.name
        for module in pkgutil.iter_modules([str(package_path)])
        if not module.name.startswith("_")
    }

    assert PUBLIC_SUBMODULES.isdisjoint(INTERNAL_SUBMODULES)
    assert discovered == PUBLIC_SUBMODULES | INTERNAL_SUBMODULES


def test_public_submodules_have_explicit_exports() -> None:
    for module_name in sorted(PUBLIC_SUBMODULES):
        module = importlib.import_module(f"quater.{module_name}")
        exports = getattr(module, "__all__", None)
        assert isinstance(exports, list)
        assert exports
        assert all(isinstance(name, str) for name in exports)


def test_version_uses_pep440_compatible_shape() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[a-z]+\d*)?", quater.__version__)


def test_py_typed_marker_is_available_to_type_checkers() -> None:
    marker = importlib.resources.files("quater").joinpath("py.typed")
    assert marker.is_file()
