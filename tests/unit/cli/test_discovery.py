from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from quater.cli.discovery import resolve_app_target
from quater.cli.errors import CLIUsageError


def write_file(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    module_name = path.with_suffix("").relative_to(root).as_posix().replace("/", ".")
    sys.modules.pop(module_name, None)
    return path


def test_discovery_resolves_importable_file_paths_and_factories(
    tmp_path: Path,
) -> None:
    write_file(tmp_path, "store/__init__.py", "")
    write_file(
        tmp_path,
        "store/api.py",
        """
        from quater import Quater

        def create_app() -> Quater:
            return Quater()
        """,
    )

    discovered = resolve_app_target("store/api.py", working_dir=tmp_path)

    assert discovered.target == "store.api:create_app"
    assert discovered.factory is True


def test_discovery_falls_back_to_dynamic_module_inspection(
    tmp_path: Path,
) -> None:
    write_file(
        tmp_path,
        "service.py",
        """
        from quater import Quater

        def build() -> Quater:
            return Quater()

        app = build()
        """,
    )

    discovered = resolve_app_target("service", working_dir=tmp_path)

    assert discovered.target == "service:app"
    assert discovered.factory is False


def test_discovery_rejects_ambiguous_app_files(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater()
        app = Quater()
        """,
    )

    with pytest.raises(CLIUsageError, match="Multiple Quater apps found"):
        resolve_app_target(None, working_dir=tmp_path)


def test_discovery_reports_unusable_app_targets(tmp_path: Path) -> None:
    with pytest.raises(CLIUsageError, match="does not exist"):
        resolve_app_target("missing.py", working_dir=tmp_path)

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    with pytest.raises(CLIUsageError, match="not a Python file"):
        resolve_app_target("package", working_dir=tmp_path)

    bad_file = write_file(
        tmp_path,
        "bad-name/main.py",
        """
        from quater import Quater

        app = Quater()
        """,
    )
    with pytest.raises(CLIUsageError, match="not importable"):
        resolve_app_target(str(bad_file), working_dir=tmp_path)


def test_discovery_reports_import_errors_without_leaking_import_tracebacks(
    tmp_path: Path,
) -> None:
    write_file(
        tmp_path,
        "broken.py",
        """
        import missing_dependency_for_quater_test
        """,
    )

    with pytest.raises(CLIUsageError, match="Could not import app module 'broken'"):
        resolve_app_target("broken", working_dir=tmp_path)
