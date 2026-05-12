from __future__ import annotations

import json

import pytest

from quater.actions.executor import ActionPreflightResult
from quater.cli.output import print_preflight


def test_preflight_human_output_shows_missing_approval_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ActionPreflightResult(
        action="update_order_status",
        source="cli",
        entrypoint="local",
        method="PATCH",
        path="/api/orders/ord_1001/status",
        arguments_hash="sha256:test",
        needs_approval=True,
        approval_token_provided=False,
        subject="admin-user",
    )

    print_preflight(result, as_json=False)

    captured = capsys.readouterr()
    assert "protected action: yes" in captured.out
    assert "approval token: missing" in captured.out
    assert "needs approval" not in captured.out
    assert "approval required" not in captured.out


def test_preflight_human_output_shows_provided_approval_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ActionPreflightResult(
        action="update_order_status",
        source="cli",
        entrypoint="local",
        method="PATCH",
        path="/api/orders/ord_1001/status",
        arguments_hash="sha256:test",
        needs_approval=True,
        approval_token_provided=True,
        subject="admin-user",
    )

    print_preflight(result, as_json=False)

    captured = capsys.readouterr()
    assert "protected action: yes" in captured.out
    assert "approval token: provided" in captured.out


def test_preflight_human_output_shows_unprotected_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ActionPreflightResult(
        action="list_catalog",
        source="cli",
        entrypoint="local",
        method="GET",
        path="/api/catalog",
        arguments_hash="sha256:test",
        needs_approval=False,
        approval_token_provided=False,
        subject="admin-user",
    )

    print_preflight(result, as_json=False)

    captured = capsys.readouterr()
    assert "protected action: no" in captured.out
    assert "approval token: not required" in captured.out


def test_preflight_json_output_keeps_machine_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = ActionPreflightResult(
        action="update_order_status",
        source="cli",
        entrypoint="server",
        method="PATCH",
        path="/api/orders/ord_1001/status",
        arguments_hash="sha256:test",
        needs_approval=True,
        approval_token_provided=False,
        subject="admin-user",
    )

    print_preflight(result, as_json=True)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["needs_approval"] is True
    assert payload["source"] == "cli"
    assert payload["entrypoint"] == "server"
    assert payload["approval_required"] is True
    assert payload["approval_token_provided"] is False
