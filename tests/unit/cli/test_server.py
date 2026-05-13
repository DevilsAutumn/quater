from __future__ import annotations

import importlib
import os
import sys
import textwrap
from pathlib import Path

import pytest

from quater.cli.main import main
from quater.cli.server import ServerOptions, serve


def write_module(tmp_path: Path, filename: str, source: str) -> None:
    sys.modules.pop(Path(filename).with_suffix("").as_posix().replace("/", "."), None)
    tmp_path.joinpath(filename).write_text(textwrap.dedent(source), encoding="utf-8")


def test_dev_runs_granian_with_reload_and_access_log_by_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[ServerOptions] = []

    def fake_serve(options: ServerOptions) -> None:
        seen.append(options)

    monkeypatch.setattr("quater.cli.main.serve", fake_serve)

    code = main(["dev", "sample:app"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert seen == [
        ServerOptions(
            target="sample:app",
            environment="development",
            host="127.0.0.1",
            port=8000,
            interface="rsgi",
            loop="auto",
            workers=1,
            reload=True,
            access_log=True,
            log_level="debug",
            factory=False,
        )
    ]


def test_dev_auto_discovers_main_py_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater()
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    assert main(["dev"]) == 0

    assert served[0].target == "main:app"
    assert served[0].factory is False
    assert served[0].reload is True


def test_dev_auto_discovers_app_py_when_main_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "app.py",
        """
        from quater import Quater

        application = Quater()
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    assert main(["dev"]) == 0

    assert served[0].target == "app:application"


def test_dev_can_discover_from_file_argument_without_colon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "service.py",
        """
        from quater import Quater

        app = Quater()
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    assert main(["dev", "service.py"]) == 0

    assert served[0].target == "service:app"


def test_dev_auto_discovers_factory_functions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        def create_app() -> Quater:
            return Quater()
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    assert main(["dev"]) == 0

    assert served[0].target == "main:create_app"
    assert served[0].factory is True


def test_dev_reports_missing_auto_discovered_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    code = main(["dev"])

    captured = capsys.readouterr()
    assert code == 2
    assert "Could not find a Quater app file" in captured.err


def test_dev_reports_app_file_syntax_error_with_source_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater(
            allowed_hosts=[*],
        )
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["dev"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "Could not inspect app file 'main.py':" in captured.err
    assert "line " in captured.err
    assert "column " in captured.err
    assert "allowed_hosts=[*]" in captured.err
    assert "^" in captured.err


def test_dev_validates_route_conflicts_before_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater()

        @app.get("/orders/{order_id}")
        async def get_order(order_id: str) -> dict[str, str]:
            return {"order_id": order_id}

        @app.patch("/orders/{id}")
        async def update_order(id: str) -> dict[str, str]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    code = main(["dev"])

    captured = capsys.readouterr()
    assert code == 2
    assert served == []
    assert "Application failed to start" in captured.err
    assert "PATCH '/orders/{id}' conflicts with GET '/orders/{order_id}'" in (
        captured.err
    )


def test_run_disables_reload_and_keeps_production_checks_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ServerOptions] = []

    def fake_serve(options: ServerOptions) -> None:
        seen.append(options)

    monkeypatch.setattr("quater.cli.main.serve", fake_serve)

    assert main(["run", "sample:app", "--host", "0.0.0.0", "--workers", "4"]) == 0

    assert seen[0].environment == "production"
    assert seen[0].host == "0.0.0.0"
    assert seen[0].workers == 4
    assert seen[0].reload is False
    assert seen[0].access_log is True
    assert seen[0].strict_production is True


def test_server_options_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ServerOptions] = []

    def fake_serve(options: ServerOptions) -> None:
        seen.append(options)

    monkeypatch.setattr("quater.cli.main.serve", fake_serve)

    code = main(
        [
            "dev",
            "sample:create_app",
            "--no-reload",
            "--no-access-log",
            "--interface",
            "asgi",
            "--loop",
            "asyncio",
            "--port",
            "9000",
            "--factory",
            "--working-dir",
            "/tmp",
        ]
    )

    assert code == 0
    assert seen[0].target == "sample:create_app"
    assert seen[0].reload is False
    assert seen[0].access_log is False
    assert seen[0].interface == "asgi"
    assert seen[0].loop == "asyncio"
    assert seen[0].port == 9000
    assert seen[0].factory is True
    assert seen[0].working_dir == Path("/tmp")


def test_serve_sets_environment_while_loading_production_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        import os
        from quater import Quater

        seen_env = os.environ.get("QUATER_ENV")
        app = Quater(
            allowed_hosts=["api.example.com"],
            docs_path=None,
            openapi_path=None,
            mcp_docs_path=None,
        )
        """,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("QUATER_ENV", raising=False)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    serve(
        ServerOptions(
            target=None,
            environment="production",
            host="127.0.0.1",
            port=8000,
            interface="rsgi",
            loop="auto",
            workers=1,
            reload=False,
            access_log=True,
            log_level="info",
            factory=False,
        )
    )

    sample = importlib.import_module("main")

    assert sample.seen_env == "production"
    assert "QUATER_ENV" not in os.environ
    assert served


def test_serve_restores_existing_environment_after_server_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater(
            allowed_hosts=["api.example.com"],
            docs_path=None,
            openapi_path=None,
            mcp_docs_path=None,
        )
        """,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QUATER_ENV", "staging")
    monkeypatch.setattr("quater.cli.server._serve_with_granian", lambda _: None)

    serve(
        ServerOptions(
            target=None,
            environment="production",
            host="127.0.0.1",
            port=8000,
            interface="rsgi",
            loop="auto",
            workers=1,
            reload=False,
            access_log=True,
            log_level="info",
            factory=False,
        )
    )

    assert os.environ["QUATER_ENV"] == "staging"


def test_run_reports_insecure_production_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater(debug=True)
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["run"])

    captured = capsys.readouterr()
    assert code == 2
    assert "Production safety check failed" in captured.err
    assert "debug must be disabled" in captured.err
    assert "allowed_hosts must be configured" in captured.err


def test_run_reports_explicit_app_import_syntax_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater(
            allowed_hosts=[*],
        )
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["run", "main:app"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "Could not import app module 'main':" in captured.err
    assert "allowed_hosts=[*]" in captured.err
    assert "Command failed" not in captured.err


def test_run_can_explicitly_skip_production_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater(debug=True)
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    code = main(["run", "--allow-insecure"])

    assert code == 0
    assert served[0].strict_production is False
    assert served[0].target == "main:app"


def test_run_allow_insecure_still_validates_routes_before_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_module(
        tmp_path,
        "main.py",
        """
        from quater import Quater

        app = Quater(debug=True)

        @app.get("/orders/{order_id}")
        async def get_order(order_id: str) -> dict[str, str]:
            return {"order_id": order_id}

        @app.patch("/orders/{id}")
        async def update_order(id: str) -> dict[str, str]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)
    served: list[ServerOptions] = []
    monkeypatch.setattr("quater.cli.server._serve_with_granian", served.append)

    code = main(["run", "--allow-insecure"])

    captured = capsys.readouterr()
    assert code == 2
    assert served == []
    assert "Application failed to start" in captured.err
    assert "PATCH '/orders/{id}' conflicts with GET '/orders/{order_id}'" in (
        captured.err
    )
