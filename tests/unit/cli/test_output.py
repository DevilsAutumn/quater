from __future__ import annotations

import json

import pytest

from quater import JSONResponse, Response
from quater.actions.executor import ActionPreflightResult
from quater.cli.output import (
    filter_action_summaries,
    print_action_envelope,
    print_action_summary_detail,
    print_action_summary_list,
    print_preflight,
    print_preflight_payload,
    print_response,
)


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


def test_action_summary_filter_searches_names_descriptions_methods_and_paths() -> None:
    summaries = [
        {
            "name": "orders.ship",
            "description": "Mark one order as shipped.",
            "method": "PATCH",
            "path": "/orders/{id}/ship",
        },
        {
            "name": "reports.sales",
            "description": "Read sales totals.",
            "method": "GET",
            "path": "/reports/sales",
        },
    ]

    assert filter_action_summaries(summaries, "PATCH") == [summaries[0]]
    assert filter_action_summaries(summaries, "sales") == [summaries[1]]
    assert filter_action_summaries(summaries, "  ") == summaries


def test_action_summary_list_outputs_compact_human_and_json_forms(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_action_summary_list([], as_json=False)
    assert capsys.readouterr().out == "No CLI actions are registered.\n"

    print_action_summary_list(
        [{"name": "health", "description": "Read service health."}],
        as_json=False,
    )
    assert capsys.readouterr().out == "health\n  Read service health.\n"

    print_action_summary_list(
        [{"name": "health", "description": "Read service health.", "path": "/health"}],
        as_json=True,
    )
    assert json.loads(capsys.readouterr().out) == {
        "actions": [{"name": "health", "description": "Read service health."}]
    }


def test_action_detail_human_output_documents_argument_shapes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = {
        "name": "reports.export",
        "description": "Export selected reports.",
        "method": "POST",
        "path": "/reports/export",
        "needs_approval": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "integer"}},
                "filters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "include_archived": {"type": "boolean"},
                    },
                    "required": ["status"],
                },
                "limit": {"type": "integer"},
            },
            "required": ["ids"],
        },
    }

    print_action_summary_detail(summary, as_json=False, remote_name="ops")

    captured = capsys.readouterr().out
    assert "reports.export" in captured
    assert "protected action: yes" in captured
    assert "--ids <json array>  required" in captured
    assert "--filters <json object>  optional" in captured
    assert "--limit <integer>  optional" in captured
    assert "quater call ops reports.export --ids '[1]'" in captured
    assert "quater call ops reports.export --dry-run --ids '[1]'" in captured
    assert (
        "quater call ops reports.export --approval APPROVAL_TOKEN --ids '[1]'"
        in captured
    )


def test_action_detail_json_output_includes_usage_and_argument_examples(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = {
        "name": "orders.create",
        "description": "Create one order.",
        "method": "POST",
        "path": "/orders",
        "needs_approval": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "order": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "quantity": {"type": "integer"},
                    },
                    "required": ["sku", "quantity"],
                }
            },
            "required": ["order"],
        },
    }

    print_action_summary_detail(summary, as_json=True, remote_name=None)

    payload = json.loads(capsys.readouterr().out)
    assert payload["arguments"] == [
        {
            "name": "order",
            "flag": "--order",
            "required": True,
            "type": "object",
            "example": '{"sku":"example","quantity":1}',
        }
    ]
    assert payload["usage"]["command"] == (
        'quater call orders.create --order \'{"sku":"example","quantity":1}\''
    )


@pytest.mark.asyncio
async def test_print_response_returns_exit_status_and_runs_finalizers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    finalized: list[str] = []

    async def finalize() -> None:
        finalized.append("closed")

    ok_response = Response(b"", status_code=204)
    ok_response._finalizers = [finalize]
    assert await print_response(ok_response, as_json=False) == 0
    assert capsys.readouterr().out == "status: 204\n"
    assert finalized == ["closed"]

    error_response = Response(b"denied", status_code=403)
    assert await print_response(error_response, as_json=True) == 1
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "status_code": 403,
        "body": "denied",
    }


@pytest.mark.asyncio
async def test_print_response_renders_json_body_not_python_repr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = JSONResponse({"id": "ord_1001", "shipped": True})

    assert await print_response(response, as_json=False) == 0

    out = capsys.readouterr().out
    assert json.loads(out) == {"id": "ord_1001", "shipped": True}
    assert "'id'" not in out  # not a Python dict repr


def test_print_action_envelope_renders_body_as_json_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_action_envelope(
        {"ok": True, "status_code": 200, "body": {"id": "ord_1001", "paid": True}},
        status_code=200,
        as_json=False,
    )

    out = capsys.readouterr().out
    assert json.loads(out) == {"id": "ord_1001", "paid": True}
    assert "'id'" not in out


def test_print_action_envelope_json_mode_keeps_full_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_action_envelope(
        {"ok": True, "status_code": 200, "body": {"id": 7}},
        status_code=200,
        as_json=True,
    )

    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "status_code": 200,
        "body": {"id": 7},
    }


def test_print_action_envelope_prints_text_body_and_empty_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_action_envelope(
        {"ok": True, "status_code": 200, "body": "pong"},
        status_code=200,
        as_json=False,
    )
    assert capsys.readouterr().out == "pong\n"

    print_action_envelope(
        {"ok": True, "status_code": 204, "body": ""},
        status_code=204,
        as_json=False,
    )
    assert capsys.readouterr().out == "status: 204\n"


def test_print_action_envelope_shows_error_envelope_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # An error envelope carries no "body"; the failure detail must survive.
    print_action_envelope(
        {"ok": False, "error": {"code": "bad_request", "message": "Missing id"}},
        status_code=400,
        as_json=False,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "error": {"code": "bad_request", "message": "Missing id"},
    }


def test_print_preflight_payload_renders_dry_run_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_preflight_payload(
        {
            "ok": True,
            "dry_run": True,
            "action": "users.lock",
            "method": "POST",
            "path": "/users/7/lock",
            "arguments_hash": "sha256:test",
            "needs_approval": True,
            "approval_token_provided": False,
        },
        as_json=False,
    )

    out = capsys.readouterr().out
    assert "Dry run OK: users.lock" in out
    assert "POST /users/7/lock" in out
    assert "protected action: yes" in out
    assert "approval token: missing" in out


def test_print_preflight_payload_shows_error_envelope_raw(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A failed dry run returns an error envelope, not a preflight payload.
    print_preflight_payload(
        {"ok": False, "error": {"code": "unknown_action", "message": "Unknown action"}},
        as_json=False,
    )
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "unknown_action"

    # Even if a non-conforming remote sets dry_run alongside ok=false, the human
    # output must not print "Dry run OK" while the call exits non-zero.
    print_preflight_payload(
        {
            "ok": False,
            "dry_run": True,
            "action": "users.lock",
            "error": {"code": "approval_denied", "message": "Denied"},
        },
        as_json=False,
    )
    out = capsys.readouterr().out
    assert "Dry run OK" not in out
    assert json.loads(out)["error"]["code"] == "approval_denied"
