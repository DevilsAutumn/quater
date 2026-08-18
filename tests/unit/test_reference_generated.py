"""Force the generated fallback path in the docs reference renderer.

The default docs pipeline hits ``read_manual_reference`` and returns the
hand-authored files in ``docs/en/dev/reference`` unchanged. Everything under
``scripts/_reference`` that describes the auth surface (option tables, field
tables, per-page prose) is only exercised when that fallback is taken. These
tests call the per-page renderers directly so table/parameter mismatches or
stale auth guidance surface as test failures instead of silently sleeping
behind the manual passthrough.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import griffe
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_paths = importlib.import_module("_reference.paths")
_render = importlib.import_module("_reference.render")

SOURCE_ROOT: Path = _paths.SOURCE_ROOT
render_application = cast(Callable[[Any], str], _render.render_application)
render_auth = cast(Callable[[Any], str], _render.render_auth)


@pytest.fixture(scope="module")
def package() -> Any:
    return griffe.load("quater", search_paths=[SOURCE_ROOT])


class TestRenderApplicationGenerated:
    """Route/group option tables must match the live signatures."""

    def test_application_page_renders(self, package: Any) -> None:
        # validated_option_table raises SystemExit on parameter mismatch, so a
        # successful render means ROUTE_OPTIONS, GROUP_ROUTE_OPTIONS, and
        # ROUTE_GROUP_OPTIONS still line up with Quater.route,
        # RouteGroup.route, and RouteGroup.__init__.
        output = render_application(package)

        assert "# Application Reference" in output
        assert "`public`" in output

    def test_application_page_does_not_document_removed_route_auth(
        self, package: Any
    ) -> None:
        output = render_application(package)

        assert "Route-level auth hook" not in output
        assert "Auth hook inherited by child routes" not in output


class TestRenderAuthGenerated:
    def test_auth_page_renders(self, package: Any) -> None:
        # field_table raises SystemExit if AuthConfig / AuthContext members
        # drift from the documented set, so a successful render is the check.
        output = render_auth(package)

        assert "# Auth and Security Reference" in output
        assert "AuthConfig" in output
        assert "AuthContext" in output

    def test_auth_page_documents_auth_context_payload(self, package: Any) -> None:
        output = render_auth(package)

        assert "`payload`" in output

    def test_auth_page_uses_current_auth_model(self, package: Any) -> None:
        output = render_auth(package)

        assert "Quater(auth=" in output
        assert "public=True" in output
        assert "mcp_auth" not in output
        assert "cli_auth" not in output
