from __future__ import annotations

import argparse
from collections.abc import Sequence

from quater.cli.client import RemoteResponse
from quater.cli.errors import CLIUsageError
from quater.cli.output import (
    filter_action_summaries,
    print_action_envelope,
    print_action_summary_detail,
    print_action_summary_list,
    print_json,
    print_preflight_payload,
)
from quater.cli.remotes import RemoteConfig, get_remote, load_remotes, save_remote
from quater.cli.utils import _non_empty_approval, _non_empty_token, _unreachable


def connect_remote(namespace: argparse.Namespace) -> int:
    name = validate_remote_name(namespace.name)
    url = validate_remote_url(namespace.url)
    token = _non_empty_token(namespace.token)
    if token is not None:
        _fetch_manifest(url, token=token)
    save_remote(RemoteConfig(name=name, url=url, token=token))
    if namespace.as_json:
        print_json({"ok": True, "remote": {"name": name, "url": url}})
    else:
        print(f"Connected remote {name}: {url}")
    return 0


def login_remote(namespace: argparse.Namespace) -> int:
    remote = get_remote(namespace.name)
    token = _non_empty_token(namespace.token)
    if token is None:
        raise CLIUsageError("--token is required")
    _fetch_manifest(remote.url, token=token)
    save_remote(RemoteConfig(name=remote.name, url=remote.url, token=token))
    if namespace.as_json:
        print_json({"ok": True, "remote": {"name": remote.name, "url": remote.url}})
    else:
        print(f"Logged in to {remote.name}")
    return 0


def list_remotes(namespace: argparse.Namespace) -> int:
    remotes = load_remotes()
    payload = {
        "remotes": [
            {
                "name": remote.name,
                "url": remote.url,
                "authenticated": bool(remote.token),
            }
            for remote in remotes.values()
        ]
    }
    if namespace.as_json:
        print_json(payload)
        return 0

    if not remotes:
        print("No remotes are configured.")
        return 0
    for remote in remotes.values():
        marker = " authenticated" if remote.token else ""
        print(f"{remote.name}  {remote.url}{marker}")
    return 0


def remote_actions(namespace: argparse.Namespace) -> int:
    remote = get_remote(namespace.remote_name)
    manifest = remote_manifest(remote, token_override=namespace.token)
    if namespace.actions_command == "list":
        actions = manifest_actions(manifest)
        print_action_summary_list(
            actions,
            as_json=namespace.as_json,
            empty_message="No remote actions are registered.",
        )
        return 0

    if namespace.actions_command == "search":
        actions = manifest_actions(manifest)
        matches = filter_action_summaries(actions, namespace.query)
        print_action_summary_list(
            matches,
            as_json=namespace.as_json,
            empty_message="No matching remote actions.",
        )
        return 0

    if namespace.actions_command == "describe":
        action = manifest_action(manifest, namespace.action_name)
        print_action_summary_detail(
            action,
            as_json=namespace.as_json,
            remote_name=remote.name,
        )
        return 0

    _unreachable()


def remote_call(namespace: argparse.Namespace, unknown: Sequence[str]) -> int:
    remote_name, action_name = namespace.target
    remote = get_remote(remote_name)
    arguments = parse_action_arguments(unknown)
    token = _non_empty_token(namespace.token) if namespace.token is not None else None
    approval_token = _non_empty_approval(namespace.approval)
    response = _call_action(
        remote.url,
        token=token or remote.token,
        action=action_name,
        arguments=arguments,
        dry_run=namespace.dry_run,
        approval_token=approval_token,
    )
    if namespace.dry_run:
        print_preflight_payload(response.body, as_json=namespace.as_json)
    else:
        print_action_envelope(
            response.body,
            status_code=response.status_code,
            as_json=namespace.as_json,
        )
    ok = response.status_code < 400 and response.body.get("ok") is not False
    return 0 if ok else 1


def remote_manifest(
    remote: RemoteConfig,
    *,
    token_override: str | None,
) -> dict[str, object]:
    token = (
        _non_empty_token(token_override) if token_override is not None else remote.token
    )
    return _fetch_manifest(remote.url, token=token)


def manifest_actions(manifest: dict[str, object]) -> list[dict[str, object]]:
    actions = manifest.get("actions")
    if not isinstance(actions, list):
        raise CLIUsageError("Remote manifest is invalid")

    validated: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, dict) or not is_action_summary(action):
            raise CLIUsageError("Remote manifest is invalid")
        validated.append(action)
    return validated


def manifest_action(
    manifest: dict[str, object],
    action_name: str,
) -> dict[str, object]:
    for action in manifest_actions(manifest):
        if action["name"] == action_name:
            return action
    raise CLIUsageError("Unknown remote action")


def is_action_summary(value: dict[object, object]) -> bool:
    return (
        isinstance(value.get("name"), str)
        and isinstance(value.get("description"), str)
        and isinstance(value.get("method"), str)
        and isinstance(value.get("path"), str)
        and isinstance(value.get("needs_approval"), bool)
        and isinstance(value.get("input_schema"), dict)
    )


def parse_action_arguments(unknown: Sequence[str]) -> dict[str, object]:
    from quater.cli.parsing import parse_action_arguments as _parse_action_arguments

    return _parse_action_arguments(unknown)


def _fetch_manifest(
    url: str,
    *,
    token: str | None,
) -> dict[str, object]:
    from quater.cli.main import fetch_manifest as main_fetch_manifest

    return main_fetch_manifest(url, token=token)


def _call_action(
    base_url: str,
    *,
    token: str | None,
    action: str,
    arguments: dict[str, object],
    dry_run: bool,
    approval_token: str | None,
) -> RemoteResponse:

    from quater.cli.main import call_action as main_call_action

    return main_call_action(
        base_url,
        token=token,
        action=action,
        arguments=arguments,
        dry_run=dry_run,
        approval_token=approval_token,
    )


def validate_remote_name(name: str) -> str:
    from quater.cli.remotes import validate_remote_name as _validate_remote_name

    return _validate_remote_name(name)


def validate_remote_url(url: str) -> str:
    from quater.cli.remotes import validate_remote_url as _validate_remote_url

    return _validate_remote_url(url)
