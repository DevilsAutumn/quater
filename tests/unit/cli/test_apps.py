from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from quater.cli.apps import load_app
from quater.cli.errors import CLIUsageError


def write_module(tmp_path: Path, source: str) -> None:
    sys.modules.pop("sample_app", None)
    tmp_path.joinpath("sample_app.py").write_text(
        textwrap.dedent(source),
        encoding="utf-8",
    )


def test_load_app_rejects_invalid_import_paths() -> None:
    with pytest.raises(CLIUsageError, match="module:attribute"):
        load_app("sample_app")

    with pytest.raises(CLIUsageError, match="module:attribute"):
        load_app(":app")

    with pytest.raises(CLIUsageError, match="module:attribute"):
        load_app("sample_app:")


def test_load_app_resolves_nested_attributes_and_factories(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        """
        from quater import Quater

        class Container:
            @staticmethod
            def make_app() -> Quater:
                return Quater(name="nested")
        """,
    )

    app = load_app(
        "sample_app:Container.make_app",
        factory=True,
        working_dir=tmp_path,
    )

    assert app.name == "nested"


def test_load_app_reports_missing_or_empty_attributes(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        """
        from quater import Quater

        app = Quater()
        """,
    )

    with pytest.raises(CLIUsageError, match="empty parts"):
        load_app("sample_app:app.", working_dir=tmp_path)

    with pytest.raises(CLIUsageError, match="Could not find app attribute"):
        load_app("sample_app:missing", working_dir=tmp_path)


def test_load_app_validates_factory_and_loaded_object_types(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        """
        value = object()

        def make_value() -> object:
            return object()
        """,
    )

    with pytest.raises(CLIUsageError, match="factory target is not callable"):
        load_app("sample_app:value", factory=True, working_dir=tmp_path)

    with pytest.raises(CLIUsageError, match="not a Quater application"):
        load_app("sample_app:make_value", factory=True, working_dir=tmp_path)

    with pytest.raises(CLIUsageError, match="not a Quater application"):
        load_app("sample_app:value", working_dir=tmp_path)


def test_load_app_reports_import_and_syntax_errors(tmp_path: Path) -> None:
    write_module(tmp_path, "import definitely_missing_quater_dependency")

    with pytest.raises(CLIUsageError, match="Could not import app module"):
        load_app("sample_app:app", working_dir=tmp_path)

    write_module(
        tmp_path,
        """
        from quater import Quater

        app = Quater(
            allowed_hosts=[*],
        )
        """,
    )

    with pytest.raises(CLIUsageError, match="Could not import app module 'sample_app'"):
        load_app("sample_app:app", working_dir=tmp_path)
