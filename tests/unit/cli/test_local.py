from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from quater.cli.main import main
from tests.unit.cli.helpers import write_app


def test_cli_lists_local_actions_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            if ctx.headers.get("authorization") == "Bearer secret":
                return AuthContext(subject="cli")
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "--token",
            "secret",
            "actions",
            "list",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "actions": [
            {
                "name": "get_user",
                "description": "Fetch one user.",
            }
        ]
    }


def test_cli_reads_local_app_and_token_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            if ctx.headers.get("authorization") == "Bearer secret":
                return AuthContext(subject="cli")
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QUATER_APP", "sample:app")
    monkeypatch.setenv("QUATER_TOKEN", "secret")

    code = main(["--json", "actions", "list"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "actions": [
            {
                "name": "get_user",
                "description": "Fetch one user.",
            }
        ]
    }


def test_cli_token_argument_overrides_environment_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            if ctx.headers.get("authorization") == "Bearer explicit":
                return AuthContext(subject="cli")
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QUATER_TOKEN", "wrong")

    code = main(
        [
            "--app",
            "sample:app",
            "--token",
            "explicit",
            "actions",
            "list",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert "get_user" in captured.out


def test_cli_rejects_empty_environment_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/health", cli=True, description="Read health.")
        async def health() -> dict[str, bool]:
            return {"ok": True}
        """,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QUATER_APP", "sample:app")
    monkeypatch.setenv("QUATER_TOKEN", " ")

    code = main(["actions", "list"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == "Auth token must not be empty\n"


def test_cli_reports_app_import_syntax_error_with_source_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, Quater, Request

        app = Quater(
            allowed_hosts=[*],
        )
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["--app", "sample:app", "actions", "list"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "Could not import app module 'sample':" in captured.err
    assert "line " in captured.err
    assert "column " in captured.err
    assert "allowed_hosts=[*]" in captured.err
    assert "Command failed" not in captured.err


def test_cli_searches_local_actions_as_compact_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}

        @app.get("/reports/sales", cli=True, description="Read sales report.")
        async def sales_report() -> dict[str, bool]:
            return {"ok": True}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "actions",
            "search",
            "sales",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == {
        "actions": [
            {
                "name": "sales_report",
                "description": "Read sales report.",
            }
        ]
    }


def test_cli_describes_local_action_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        import msgspec
        from quater import AuthConfig, AuthContext, Quater, Request

        class CreateUser(msgspec.Struct):
            name: str
            age: int
            newsletter: bool = False

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.post("/users", cli=True, description="Create one user.")
        async def create_user(user: CreateUser) -> dict[str, object]:
            return {"name": user.name, "age": user.age}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "actions",
            "describe",
            "create_user",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["name"] == "create_user"
    assert payload["usage"]["command"] == (
        'quater call create_user --user \'{"name":"example","age":1}\''
    )
    assert payload["arguments"] == [
        {
            "name": "user",
            "flag": "--user",
            "required": True,
            "type": "object",
            "example": '{"name":"example","age":1}',
        }
    ]
    assert "dry_run_command" in payload["usage"]
    assert payload["input_schema"]["required"] == ["user"]


def test_cli_actions_are_protected_by_cli_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["--app", "sample:app", "actions", "list"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "Unauthorized\n"


def test_cli_call_executes_action_with_typed_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        import msgspec
        from quater import AuthConfig, AuthContext, Quater, Request

        class CreateUser(msgspec.Struct):
            name: str
            age: int

        async def cli_auth(ctx: Request) -> AuthContext | None:
            if ctx.headers.get("authorization") == "Bearer secret":
                return AuthContext(subject="cli")
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.post("/users", cli=True, description="Create one user.")
        async def create_user(user: CreateUser) -> dict[str, object]:
            return {"name": user.name, "age": user.age}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "--token",
            "secret",
            "call",
            "create_user",
            "--user",
            '{"name":"Ada","age":37}',
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload == {
        "ok": True,
        "status_code": 200,
        "body": {"name": "Ada", "age": 37},
    }


def test_cli_call_runs_global_middleware_on_local_action_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import (
            AuthConfig,
            AuthContext,
            Quater,
            Request,
            Response,
            TextResponse,
        )

        events: list[str] = []

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.after_response
        async def global_after(request: Request, response: Response) -> Response:
            events.append(f"{request.path}:{response.body.decode()}")
            return TextResponse("after saw handler response")

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "call",
            "get_user",
            "--id",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == {
        "ok": True,
        "status_code": 200,
        "body": "after saw handler response",
    }

    sample = importlib.import_module("sample")

    assert sample.events == ['/users/7:{"id":7}']


def test_cli_call_rejects_empty_approval_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        async def approve(ctx) -> bool:
            return True

        app = Quater(
            auth=[AuthConfig(cli_auth, surfaces=["cli"])],
            action_approval=approve,
        )

        @app.post(
            "/users/{id:int}/lock",
            cli=True,
            needs_approval=True,
            description="Lock one user.",
        )
        async def lock_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "call",
            "lock_user",
            "--approval",
            " ",
            "--id",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == "Approval token must not be empty\n"


def test_cli_call_auth_sees_local_entrypoint_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        seen_contexts: list[tuple[str, str, str | None]] = []

        async def cli_auth(ctx: Request) -> AuthContext | None:
            seen_contexts.append((
                ctx.context.source,
                ctx.context.entrypoint,
                ctx.context.action_name,
            ))
            if ctx.headers.get("authorization") == "Bearer secret":
                return AuthContext(subject="cli")
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int, request: Request) -> dict[str, object]:
            return {
                "id": id,
                "source": request.context.source,
                "entrypoint": request.context.entrypoint,
                "action": request.context.action_name,
            }
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "--token",
            "secret",
            "call",
            "get_user",
            "--id",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["body"] == {
        "id": 7,
        "source": "cli",
        "entrypoint": "local",
        "action": "get_user",
    }

    sample = importlib.import_module("sample")

    assert sample.seen_contexts == [("cli", "local", "get_user")]


def test_cli_dry_run_validates_but_does_not_call_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        calls = 0

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            global calls
            calls += 1
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--app",
            "sample:app",
            "--json",
            "call",
            "get_user",
            "--dry-run",
            "--id",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["dry_run"] is True
    assert payload["path"] == "/users/7"
    assert payload["approval_required"] is False

    sample = importlib.import_module("sample")

    assert sample.calls == 0


def test_cli_call_requires_cli_auth_before_handler_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        calls = 0

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return None

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            global calls
            calls += 1
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["--app", "sample:app", "call", "get_user", "--id", "7"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "Unauthorized\n"

    sample = importlib.import_module("sample")

    assert sample.calls == 0


def test_cli_call_cannot_execute_non_cli_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.get("/health")
        async def health() -> dict[str, bool]:
            return {"ok": True}

        @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
        async def get_user(id: int) -> dict[str, int]:
            return {"id": id}
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["--app", "sample:app", "call", "health"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == "Unknown CLI action\n"


def test_cli_handler_errors_do_not_leak_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import AuthConfig, AuthContext, Quater, Request

        async def cli_auth(ctx: Request) -> AuthContext | None:
            return AuthContext(subject="cli")

        app = Quater(auth=[AuthConfig(cli_auth, surfaces=["cli"])])

        @app.post("/danger", cli=True, description="Run dangerous action.")
        async def danger() -> dict[str, bool]:
            raise RuntimeError("database password is secret")
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["--app", "sample:app", "call", "danger"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "Command failed\n"
