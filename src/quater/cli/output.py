"""Output formatting for CLI commands."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import TextIO

from quater._finalize import run_response_finalizers
from quater.actions.executor import ActionPreflightResult
from quater.actions.registry import ActionDefinition
from quater.protocol.actions import (
    action_summary,
    preflight_payload,
    response_payload,
)
from quater.response import Response
from quater.serialization import dumps_json, dumps_pretty_json

ActionSummary = Mapping[str, object]


def print_json(value: object, *, file: TextIO | None = None) -> None:
    if file is None:
        file = sys.stdout
    file.write(dumps_pretty_json(value).decode("utf-8"))
    file.write("\n")


def action_summaries(actions: Iterable[ActionDefinition]) -> list[dict[str, object]]:
    return [action_summary(action) for action in actions]


def filter_action_summaries(
    summaries: Iterable[ActionSummary],
    query: str,
) -> list[ActionSummary]:
    needle = query.strip().casefold()
    if not needle:
        return list(summaries)
    return [
        summary for summary in summaries if needle in _searchable_action_text(summary)
    ]


def print_action_summary_list(
    summaries: Iterable[ActionSummary],
    *,
    as_json: bool,
    empty_message: str = "No CLI actions are registered.",
) -> None:
    compact = [compact_action_summary(summary) for summary in summaries]
    if as_json:
        print_json({"actions": compact})
        return

    if not compact:
        print(empty_message)
        return

    for action in compact:
        print(f"{action['name']}\n  {action['description']}")


def compact_action_summary(summary: ActionSummary) -> dict[str, str]:
    return {
        "name": _summary_string(summary, "name"),
        "description": _summary_string(summary, "description"),
    }


def print_action_detail(
    action: ActionDefinition,
    *,
    as_json: bool,
    remote_name: str | None = None,
) -> None:
    summary = action_summary(action)
    print_action_summary_detail(summary, as_json=as_json, remote_name=remote_name)


def print_action_summary_detail(
    summary: ActionSummary,
    *,
    as_json: bool,
    remote_name: str | None = None,
) -> None:
    usage = _usage(summary, remote_name=remote_name)
    if as_json:
        detail = dict(summary)
        detail["arguments"] = _argument_payloads(_summary_schema(summary))
        detail["usage"] = usage
        print_json(detail)
        return

    print(_summary_string(summary, "name"))
    print(f"  {_summary_string(summary, 'method')} {_summary_string(summary, 'path')}")
    print(f"  {_summary_string(summary, 'description')}")
    print(f"  protected action: {_yes_no(_summary_bool(summary, 'needs_approval'))}")
    print("  arguments:")
    _print_action_arguments(_summary_schema(summary))
    print("  usage:")
    print(f"    {usage['command']}")
    print("  dry run:")
    print(f"    {usage['dry_run_command']}")
    approval_command = usage.get("approval_command")
    if isinstance(approval_command, str):
        print("  with approval:")
        print(f"    {approval_command}")
    print("  input schema:")
    print(dumps_pretty_json(_summary_schema(summary)).decode("utf-8"))


def print_preflight(result: ActionPreflightResult, *, as_json: bool) -> None:
    print_preflight_payload(preflight_payload(result), as_json=as_json)


def print_preflight_payload(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print_json(payload)
        return

    if not _summary_bool(payload, "dry_run") or not _summary_bool(payload, "ok"):
        # Error or non-preflight payload — show it raw, never "Dry run OK".
        print_json(payload)
        return

    print(f"Dry run OK: {_summary_string(payload, 'action')}")
    print(f"  {_summary_string(payload, 'method')} {_summary_string(payload, 'path')}")
    print(f"  arguments hash: {_summary_string(payload, 'arguments_hash')}")
    print(f"  protected action: {_yes_no(_summary_bool(payload, 'needs_approval'))}")
    print(f"  approval token: {_payload_approval_token_status(payload)}")


async def print_response(response: Response, *, as_json: bool) -> int:
    try:
        payload = await response_payload(response)
    finally:
        await run_response_finalizers(response)
    print_action_envelope(payload, status_code=response.status_code, as_json=as_json)
    return 0 if response.status_code < 400 else 1


def print_action_envelope(
    envelope: Mapping[str, object],
    *,
    status_code: int,
    as_json: bool,
) -> None:
    if as_json:
        print_json(envelope)
        return

    if "body" in envelope:
        _print_response_body(envelope["body"], status_code=status_code)
    else:
        # Error envelope ({"ok": false, "error": {...}}) carries no body — show
        # the whole thing so the failure detail is not swallowed.
        print_json(envelope)


def _print_response_body(body: object, *, status_code: int) -> None:
    if isinstance(body, str):
        if body:
            print(body)
        else:
            print(f"status: {status_code}")
        return
    print_json(body)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _payload_approval_token_status(payload: Mapping[str, object]) -> str:
    if not _summary_bool(payload, "needs_approval"):
        return "not required"
    if _summary_bool(payload, "approval_token_provided"):
        return "provided"
    return "missing"


def _searchable_action_text(summary: ActionSummary) -> str:
    values = [
        _summary_string(summary, "name"),
        _summary_string(summary, "description"),
        _summary_string(summary, "method"),
        _summary_string(summary, "path"),
    ]
    return " ".join(values).casefold()


def _summary_string(
    summary: ActionSummary,
    key: str,
    default: str = "",
) -> str:
    value = summary.get(key)
    return value if isinstance(value, str) else default


def _summary_bool(summary: ActionSummary, key: str) -> bool:
    value = summary.get(key)
    return value if isinstance(value, bool) else False


def _summary_schema(summary: ActionSummary) -> Mapping[str, object]:
    value = summary.get("input_schema")
    return value if isinstance(value, Mapping) else {}


def _usage(
    summary: ActionSummary,
    *,
    remote_name: str | None,
) -> dict[str, object]:
    usage: dict[str, object] = {
        "argument_style": (
            "Pass each input property as --kebab-case-name value. "
            "JSON objects and arrays must be valid JSON strings."
        ),
        "command": _usage_command(summary, remote_name=remote_name),
        "dry_run_command": _usage_command(
            summary,
            remote_name=remote_name,
            dry_run=True,
        ),
    }
    if _summary_bool(summary, "needs_approval"):
        usage["approval_command"] = _usage_command(
            summary,
            remote_name=remote_name,
            approval=True,
        )
    return usage


def _usage_command(
    summary: ActionSummary,
    *,
    remote_name: str | None,
    dry_run: bool = False,
    approval: bool = False,
) -> str:
    parts = ["quater", "call"]
    if remote_name is not None:
        parts.append(remote_name)
    parts.append(_summary_string(summary, "name"))
    if dry_run:
        parts.append("--dry-run")
    if approval and _summary_bool(summary, "needs_approval"):
        parts.extend(["--approval", "APPROVAL_TOKEN"])

    for argument in _required_argument_examples(_summary_schema(summary)):
        parts.extend([argument.flag, argument.example])

    return shlex.join(parts)


class _ArgumentExample:
    __slots__ = ("example", "flag", "name", "required", "schema")

    def __init__(
        self,
        *,
        name: str,
        flag: str,
        example: str,
        required: bool,
        schema: Mapping[str, object],
    ) -> None:
        self.name = name
        self.flag = flag
        self.example = example
        self.required = required
        self.schema = schema


def _print_action_arguments(schema: Mapping[str, object]) -> None:
    arguments = _argument_examples(schema)
    if not arguments:
        print("    none")
        return

    for argument in arguments:
        requirement = "required" if argument.required else "optional"
        print(
            f"    {argument.flag} {_schema_placeholder(argument.schema)}  {requirement}"
        )


def _required_argument_examples(
    schema: Mapping[str, object],
) -> list[_ArgumentExample]:
    return [argument for argument in _argument_examples(schema) if argument.required]


def _argument_examples(schema: Mapping[str, object]) -> list[_ArgumentExample]:
    properties = _schema_properties(schema)
    required = _schema_required(schema)
    arguments: list[_ArgumentExample] = []
    for name, field_schema in properties.items():
        if not isinstance(field_schema, Mapping):
            continue
        arguments.append(
            _ArgumentExample(
                name=name,
                flag=f"--{name.replace('_', '-')}",
                example=_example_cli_value(field_schema),
                required=name in required,
                schema=field_schema,
            )
        )
    return arguments


def _argument_payloads(schema: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {
            "name": argument.name,
            "flag": argument.flag,
            "required": argument.required,
            "type": _schema_type(argument.schema),
            "example": argument.example,
        }
        for argument in _argument_examples(schema)
    ]


def _schema_properties(schema: Mapping[str, object]) -> Mapping[str, object]:
    value = schema.get("properties")
    return value if isinstance(value, Mapping) else {}


def _schema_required(schema: Mapping[str, object]) -> set[str]:
    value = schema.get("required")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return set()
    return {item for item in value if isinstance(item, str)}


def _schema_type(schema: Mapping[str, object]) -> str:
    value = schema.get("type")
    return value if isinstance(value, str) else "object"


def _schema_placeholder(schema: Mapping[str, object]) -> str:
    schema_type = _schema_type(schema)
    if schema_type == "integer":
        return "<integer>"
    if schema_type == "number":
        return "<number>"
    if schema_type == "boolean":
        return "<true|false>"
    if schema_type == "array":
        return "<json array>"
    if schema_type == "object":
        return "<json object>"
    return "<string>"


def _example_cli_value(schema: Mapping[str, object]) -> str:
    schema_type = _schema_type(schema)
    if schema_type == "integer":
        return "1"
    if schema_type == "number":
        return "1.0"
    if schema_type == "boolean":
        return "true"
    if schema_type in {"array", "object"}:
        return dumps_json(_json_example(schema)).decode("utf-8")
    return "example"


def _json_example(schema: Mapping[str, object]) -> object:
    schema_type = _schema_type(schema)
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, Mapping):
            return [_json_example(items)]
        return []
    if schema_type != "object":
        return "example"

    properties = _schema_properties(schema)
    required = _schema_required(schema)
    selected_names = required if required else set(properties)
    return {
        name: _json_example(field_schema)
        for name, field_schema in properties.items()
        if name in selected_names and isinstance(field_schema, Mapping)
    }
