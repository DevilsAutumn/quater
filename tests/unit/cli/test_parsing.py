from __future__ import annotations

import pytest

from quater.cli.errors import CLIUsageError
from quater.cli.parsing import parse_action_arguments, parse_headers


def test_cli_rejects_duplicate_dynamic_arguments() -> None:
    with pytest.raises(CLIUsageError, match="Duplicate action argument --id"):
        parse_action_arguments(["--id", "1", "--id", "2"])


def test_cli_parses_json_scalars_and_objects() -> None:
    assert parse_action_arguments(
        [
            "--id",
            "7",
            "--active",
            "true",
            "--user",
            '{"name":"Ada"}',
        ]
    ) == {
        "id": 7,
        "active": True,
        "user": {"name": "Ada"},
    }


def test_cli_keeps_plain_strings_unparsed() -> None:
    # Bare words are not JSON-shaped and must be preserved verbatim, including
    # values with spaces or leading zeros that should not become numbers.
    assert parse_action_arguments(
        ["--name", "Ada", "--note", "hello world", "--code", "007"]
    ) == {
        "name": "Ada",
        "note": "hello world",
        "code": "007",
    }


def test_cli_accepts_inline_equals_form() -> None:
    assert parse_action_arguments(["--id=7", "--name=Ada"]) == {
        "id": 7,
        "name": "Ada",
    }


def test_cli_inline_equals_keeps_empty_and_embedded_equals() -> None:
    assert parse_action_arguments(["--filter=", "--expr=a=b"]) == {
        "filter": "",
        "expr": "a=b",
    }


def test_cli_normalizes_dashes_in_argument_names() -> None:
    assert parse_action_arguments(["--order-id", "ord_1"]) == {"order_id": "ord_1"}


def test_cli_double_dash_separator_is_skipped() -> None:
    assert parse_action_arguments(["--", "--id", "9"]) == {"id": 9}


def test_cli_rejects_positional_argument() -> None:
    with pytest.raises(CLIUsageError, match="Unexpected action argument 'list'"):
        parse_action_arguments(["list"])


def test_cli_rejects_non_identifier_argument_name() -> None:
    with pytest.raises(CLIUsageError, match="Invalid action argument name --1st"):
        parse_action_arguments(["--1st", "x"])


def test_cli_rejects_invalid_json_like_values() -> None:
    with pytest.raises(CLIUsageError, match="Invalid JSON value"):
        parse_action_arguments(["--user", '{"name":'])


def test_cli_rejects_missing_dynamic_argument_value() -> None:
    with pytest.raises(CLIUsageError, match="Missing value"):
        parse_action_arguments(["--id"])


def test_cli_followed_by_flag_is_missing_value() -> None:
    # A value that itself starts with -- is treated as the next flag, so the
    # preceding flag is reported as missing rather than swallowing it.
    with pytest.raises(CLIUsageError, match="Missing value for action argument --id"):
        parse_action_arguments(["--id", "--name", "Ada"])


def test_cli_collects_custom_headers() -> None:
    assert parse_headers(
        token=None,
        headers=["X-Trace: abc123", "Accept: application/json"],
    ) == {
        "x-trace": "abc123",
        "accept": "application/json",
    }


def test_cli_token_sets_authorization_header() -> None:
    assert parse_headers(token="secret", headers=[]) == {
        "authorization": "Bearer secret"
    }


def test_cli_rejects_invalid_header_shape() -> None:
    with pytest.raises(CLIUsageError, match="Headers must be provided"):
        parse_headers(token=None, headers=["Authorization"])


def test_cli_rejects_conflicting_authorization_inputs() -> None:
    with pytest.raises(CLIUsageError, match="Use either --token"):
        parse_headers(token="secret", headers=["Authorization: Bearer other"])


def test_cli_rejects_empty_token() -> None:
    with pytest.raises(CLIUsageError, match="Auth token must not be empty"):
        parse_headers(token=" ", headers=[])
