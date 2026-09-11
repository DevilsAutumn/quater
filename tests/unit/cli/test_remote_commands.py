from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from quater.cli.client import RemoteResponse
from quater.cli.main import main
from tests.unit.cli.helpers import file_mode


def test_cli_rejects_insecure_remote_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QUATER_HOME", str(tmp_path / ".quater"))

    code = main(["connect", "billing", "http://api.example.com", "--token", "secret"])

    captured = capsys.readouterr()
    assert code == 2
    assert "HTTPS" in captured.err


def test_cli_connect_stores_remote_with_strict_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_tokens: list[str | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        seen_tokens.append(token)
        return {"protocol": "quater-actions.v1", "actions": []}

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    code = main(
        [
            "--json",
            "connect",
            "billing",
            "https://api.example.com",
            "--token",
            "secret",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "secret" not in captured.out
    assert seen_tokens == ["secret"]
    config_path = quater_home / "remotes.json"
    assert file_mode(config_path) == 0o600
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["remotes"]["billing"]["url"] == "https://api.example.com"
    assert payload["remotes"]["billing"]["token"] == "secret"
    assert "manifest" not in payload["remotes"]["billing"]


def test_cli_login_validates_token_without_storing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_tokens: list[str | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        seen_tokens.append(token)
        return {"protocol": "quater-actions.v1", "actions": []}

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert main(["connect", "billing", "https://api.example.com"]) == 0
    capsys.readouterr()

    code = main(["login", "billing", "--token", "secret"])

    captured = capsys.readouterr()
    assert code == 0
    assert "secret" not in captured.out
    assert seen_tokens == ["secret"]
    payload = json.loads((quater_home / "remotes.json").read_text(encoding="utf-8"))
    assert payload["remotes"]["billing"] == {
        "token": "secret",
        "url": "https://api.example.com",
    }


def test_cli_remote_actions_list_uses_stored_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_tokens: list[str | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        seen_tokens.append(token)
        return {
            "protocol": "quater-actions.v1",
            "actions": [
                {
                    "name": "users.get",
                    "description": "Fetch one user.",
                    "method": "GET",
                    "path": "/users/{id:int}",
                    "needs_approval": False,
                    "input_schema": {},
                }
            ],
        }

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(["--json", "actions", "list", "billing"])

    captured = capsys.readouterr()
    assert code == 0
    assert seen_tokens == ["secret", "secret"]
    payload = json.loads(captured.out)
    assert payload == {
        "actions": [
            {
                "name": "users.get",
                "description": "Fetch one user.",
            }
        ]
    }
    config_payload = json.loads(
        (quater_home / "remotes.json").read_text(encoding="utf-8")
    )
    assert "manifest" not in config_payload["remotes"]["billing"]


def test_cli_remote_actions_search_keeps_results_compact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            "protocol": "quater-actions.v1",
            "actions": [
                {
                    "name": "users.get",
                    "description": "Fetch one user.",
                    "method": "GET",
                    "path": "/users/{id:int}",
                    "needs_approval": False,
                    "input_schema": {},
                },
                {
                    "name": "orders.ship",
                    "description": "Mark an order as shipped.",
                    "method": "PATCH",
                    "path": "/orders/{id}/ship",
                    "needs_approval": True,
                    "input_schema": {},
                },
            ],
        }

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(["--json", "actions", "search", "billing", "ship"])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == {
        "actions": [
            {
                "name": "orders.ship",
                "description": "Mark an order as shipped.",
            }
        ]
    }


def test_cli_remote_actions_describe_includes_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            "protocol": "quater-actions.v1",
            "actions": [
                {
                    "name": "orders.update_status",
                    "description": "Update an order status.",
                    "method": "PATCH",
                    "path": "/orders/{order_id}/status",
                    "needs_approval": True,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string"},
                            "status": {"type": "string"},
                            "notify_customer": {"type": "boolean"},
                        },
                        "required": ["order_id", "status"],
                        "additionalProperties": False,
                    },
                }
            ],
        }

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "--json",
            "actions",
            "describe",
            "billing",
            "orders.update_status",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["arguments"] == [
        {
            "name": "order_id",
            "flag": "--order-id",
            "required": True,
            "type": "string",
            "example": "example",
        },
        {
            "name": "status",
            "flag": "--status",
            "required": True,
            "type": "string",
            "example": "example",
        },
        {
            "name": "notify_customer",
            "flag": "--notify-customer",
            "required": False,
            "type": "boolean",
            "example": "true",
        },
    ]
    assert payload["usage"]["command"] == (
        "quater call billing orders.update_status --order-id example --status example"
    )
    assert "kebab-case" in payload["usage"]["argument_style"]
    assert payload["usage"]["approval_command"] == (
        "quater call billing orders.update_status --approval APPROVAL_TOKEN "
        "--order-id example --status example"
    )


def test_cli_remote_call_sends_arguments_and_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen: list[dict[str, object]] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {"protocol": "quater-actions.v1", "actions": []}

    def fake_call_action(
        base_url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        action: str,
        arguments: dict[str, object],
        dry_run: bool,
        approval_token: str | None,
    ) -> RemoteResponse:
        seen.append(
            {
                "base_url": base_url,
                "token": token,
                "action": action,
                "arguments": arguments,
                "dry_run": dry_run,
                "approval_token": approval_token,
            }
        )
        return RemoteResponse(
            status_code=200,
            body={"ok": True, "body": {"id": 7}},
        )

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)
    monkeypatch.setattr("quater.cli.main.call_action", fake_call_action)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "--json",
            "call",
            "billing",
            "users.lock",
            "--dry-run",
            "--approval",
            "approved",
            "--id",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert seen == [
        {
            "base_url": "https://api.example.com",
            "token": "secret",
            "action": "users.lock",
            "arguments": {"id": 7},
            "dry_run": True,
            "approval_token": "approved",
        }
    ]
    assert json.loads(captured.out)["ok"] is True


def _stub_remote_call(
    monkeypatch: pytest.MonkeyPatch,
    response: RemoteResponse,
) -> None:
    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {"protocol": "quater-actions.v1", "actions": []}

    def fake_call_action(
        base_url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        action: str,
        arguments: dict[str, object],
        dry_run: bool,
        approval_token: str | None,
    ) -> RemoteResponse:
        return response

    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)
    monkeypatch.setattr("quater.cli.main.call_action", fake_call_action)


def test_cli_remote_call_unwraps_body_unless_json_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QUATER_HOME", str(tmp_path / ".quater"))
    _stub_remote_call(
        monkeypatch,
        RemoteResponse(status_code=200, body={"ok": True, "body": {"id": 7}}),
    )

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    assert main(["call", "billing", "users.get", "--id", "7"]) == 0
    default_out = capsys.readouterr().out

    assert main(["--json", "call", "billing", "users.get", "--id", "7"]) == 0
    json_out = capsys.readouterr().out

    # The --json flag controls envelope-vs-body: default unwraps to the action
    # body, --json keeps the full RPC envelope. The two must differ, which is the
    # behavior the old code (always printing the envelope) got wrong.
    assert json.loads(default_out) == {"id": 7}
    assert "'id'" not in default_out  # not a Python repr
    assert json.loads(json_out) == {"ok": True, "body": {"id": 7}}
    assert default_out != json_out


def test_cli_remote_call_error_envelope_is_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QUATER_HOME", str(tmp_path / ".quater"))
    _stub_remote_call(
        monkeypatch,
        RemoteResponse(
            status_code=400,
            body={"ok": False, "error": {"code": "bad_request", "message": "Bad id"}},
        ),
    )

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(["call", "billing", "users.get", "--id", "x"])

    captured = capsys.readouterr()
    assert code == 1
    # No "body" key on an error envelope — the failure detail must still surface.
    assert json.loads(captured.out)["error"]["code"] == "bad_request"


def test_cli_remote_call_dry_run_matches_local_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QUATER_HOME", str(tmp_path / ".quater"))
    _stub_remote_call(
        monkeypatch,
        RemoteResponse(
            status_code=200,
            body={
                "ok": True,
                "dry_run": True,
                "action": "users.lock",
                "method": "POST",
                "path": "/users/7/lock",
                "arguments_hash": "sha256:test",
                "needs_approval": True,
                "approval_token_provided": False,
            },
        ),
    )

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(["call", "billing", "users.lock", "--dry-run", "--id", "7"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Dry run OK: users.lock" in captured.out
    assert "POST /users/7/lock" in captured.out
    assert "arguments hash: sha256:test" in captured.out
    assert "protected action: yes" in captured.out
    assert "approval token: missing" in captured.out


def test_cli_remote_call_rejects_empty_token_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {"protocol": "quater-actions.v1", "actions": []}

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(["--token", " ", "call", "billing", "users.get", "--id", "7"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == "Token must not be empty\n"


def test_cli_remote_call_rejects_empty_approval_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {"protocol": "quater-actions.v1", "actions": []}

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "call",
            "billing",
            "users.lock",
            "--approval",
            " ",
            "--id",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == "Approval token must not be empty\n"


def test_cli_remote_actions_list_forwards_custom_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_headers: list[Mapping[str, str] | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        seen_headers.append(headers)
        return {"protocol": "quater-actions.v1", "actions": []}

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "--header",
            "X-Operator: admin",
            "actions",
            "list",
            "billing",
        ]
    )

    capsys.readouterr()
    assert code == 0
    assert len(seen_headers) == 2
    assert seen_headers[1] == {
        "authorization": "Bearer secret",
        "x-operator": "admin",
    }


def test_cli_remote_call_forwards_custom_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_headers: list[Mapping[str, str] | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        return {"protocol": "quater-actions.v1", "actions": []}

    def fake_call_action(
        base_url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        action: str,
        arguments: dict[str, object],
        dry_run: bool,
        approval_token: str | None,
    ) -> RemoteResponse:
        seen_headers.append(headers)
        return RemoteResponse(status_code=200, body={"ok": True, "body": {"id": 7}})

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)
    monkeypatch.setattr("quater.cli.main.call_action", fake_call_action)

    assert (
        main(["connect", "billing", "https://api.example.com", "--token", "secret"])
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "--header",
            "X-Operator: admin",
            "call",
            "billing",
            "users.get",
            "--id",
            "7",
        ]
    )

    capsys.readouterr()
    assert code == 0
    assert seen_headers == [
        {
            "authorization": "Bearer secret",
            "x-operator": "admin",
        }
    ]


def test_cli_remote_rejects_malformed_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QUATER_HOME", str(tmp_path / ".quater"))

    code = main(["--header", "InvalidHeader", "actions", "list", "billing"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == "Headers must be provided as 'Name: value'\n"


def test_cli_remote_rejects_conflicting_token_and_auth_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QUATER_HOME", str(tmp_path / ".quater"))

    code = main(
        [
            "--token",
            "secret",
            "--header",
            "Authorization: Bearer other",
            "actions",
            "list",
            "billing",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == "Use either --token or an Authorization header\n"


def test_cli_remote_custom_auth_header_overrides_stored_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_headers: list[Mapping[str, str] | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        seen_headers.append(headers)
        return {"protocol": "quater-actions.v1", "actions": []}

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert (
        main(
            [
                "connect",
                "billing",
                "https://api.example.com",
                "--token",
                "stored-secret",
            ]
        )
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "--header",
            "Authorization: Bearer explicit-token",
            "actions",
            "list",
            "billing",
        ]
    )

    capsys.readouterr()
    assert code == 0
    assert len(seen_headers) == 2
    assert seen_headers[1] == {
        "authorization": "Bearer explicit-token",
    }


def test_cli_remote_actions_search_and_describe_forward_custom_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quater_home = tmp_path / ".quater"
    seen_headers: list[Mapping[str, str] | None] = []

    def fake_fetch_manifest(
        url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        seen_headers.append(headers)
        return {
            "protocol": "quater-actions.v1",
            "actions": [
                {
                    "name": "orders.get",
                    "description": "Fetch one order.",
                    "method": "GET",
                    "path": "/orders/{id:int}",
                    "needs_approval": False,
                    "input_schema": {},
                }
            ],
        }

    monkeypatch.setenv("QUATER_HOME", str(quater_home))
    monkeypatch.setattr("quater.cli.main.fetch_manifest", fake_fetch_manifest)

    assert main(["connect", "store", "https://api.example.com"]) == 0
    capsys.readouterr()

    # Test actions search forwards custom header
    code_search = main(
        [
            "--header",
            "X-Operator: admin",
            "actions",
            "search",
            "store",
            "order",
        ]
    )
    capsys.readouterr()
    assert code_search == 0

    # Test actions describe forwards custom header
    code_describe = main(
        [
            "--header",
            "X-Operator: admin",
            "actions",
            "describe",
            "store",
            "orders.get",
        ]
    )
    capsys.readouterr()
    assert code_describe == 0

    assert len(seen_headers) == 2
    assert seen_headers[0] == {"x-operator": "admin"}
    assert seen_headers[1] == {"x-operator": "admin"}
