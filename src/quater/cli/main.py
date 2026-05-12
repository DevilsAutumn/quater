"""Command line entrypoint for Quater."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, cast

from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition
from quater.auth import authenticate_request
from quater.cli.apps import load_app
from quater.cli.client import call_action, fetch_manifest
from quater.cli.errors import CLIError, CLIUsageError
from quater.cli.output import (
    action_summaries,
    filter_action_summaries,
    print_action_detail,
    print_action_summary_detail,
    print_action_summary_list,
    print_json,
    print_preflight,
    print_response,
)
from quater.cli.parsing import parse_action_arguments, parse_headers
from quater.cli.remotes import (
    RemoteConfig,
    get_remote,
    load_remotes,
    save_remote,
    validate_remote_name,
    validate_remote_url,
)
from quater.cli.server import (
    ServerEnvironment,
    ServerInterface,
    ServerLogLevel,
    ServerLoop,
    ServerOptions,
    serve,
)
from quater.exceptions import HTTPError, QuaterError
from quater.protocol.actions import ACTIONS_RPC_PATH
from quater.request import Request
from quater.typing import RequestContext


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        namespace, unknown = parser.parse_known_args(argv)
        if namespace.command != "call" and unknown:
            parser.error(f"unrecognized arguments: {' '.join(unknown)}")
        return asyncio.run(_run(namespace, unknown))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    except CLIError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except HTTPError as exc:
        print(exc.detail, file=sys.stderr)
        return 1
    except QuaterError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("Command failed", file=sys.stderr)
        return 1


async def _run(namespace: argparse.Namespace, unknown: Sequence[str]) -> int:
    if namespace.command in {"dev", "run"}:
        serve(_server_options(namespace))
        return 0
    if namespace.command == "connect":
        return _connect_remote(namespace)
    if namespace.command == "login":
        return _login_remote(namespace)
    if namespace.command == "remotes":
        return _list_remotes(namespace)

    if namespace.command == "actions" and getattr(namespace, "remote_name", None):
        return _remote_actions(namespace)
    if namespace.command == "call" and len(namespace.target) == 2:
        return _remote_call(namespace, unknown)

    app_path = namespace.app or os.environ.get("QUATER_APP")
    if app_path is None:
        raise CLIUsageError("--app is required unless QUATER_APP is set")

    app = load_app(app_path)
    headers = parse_headers(token=namespace.token, headers=namespace.header)
    registry = app._compiled_action_registry()
    if namespace.command == "actions":
        await _authenticate_actions_request(app, headers)
        summaries = action_summaries(registry.cli_actions())
        if namespace.actions_command == "list":
            print_action_summary_list(summaries, as_json=namespace.as_json)
            return 0
        if namespace.actions_command == "search":
            matches = filter_action_summaries(summaries, namespace.query)
            print_action_summary_list(
                matches,
                as_json=namespace.as_json,
                empty_message="No matching CLI actions.",
            )
            return 0
        if namespace.actions_command == "describe":
            action = _get_cli_action(registry.get(namespace.action_name))
            print_action_detail(action, as_json=namespace.as_json)
            return 0
        _unreachable()

    if namespace.command == "call":
        if len(namespace.target) != 1:
            raise CLIUsageError("Local calls must specify exactly one action")
        action = _get_cli_action(registry.get(namespace.target[0]))
        arguments = parse_action_arguments(unknown)
        request = Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers=headers,
            context=RequestContext(
                source="cli",
                entrypoint="local",
                action_name=action.name,
            ),
        )
        approval_token = _non_empty_approval(namespace.approval)
        if namespace.dry_run:
            result = await preflight_action(
                action,
                request,
                arguments,
                source="cli",
                surface_auth=app.cli_auth,
                approval_token=approval_token,
            )
            print_preflight(result, as_json=namespace.as_json)
            return 0

        response = await execute_action(
            action,
            request,
            arguments,
            source="cli",
            surface_auth=app.cli_auth,
            approval_hook=app.action_approval,
            approval_token=approval_token,
            debug=app.config.debug,
        )
        return await print_response(response, as_json=namespace.as_json)

    _unreachable()


def _connect_remote(namespace: argparse.Namespace) -> int:
    name = validate_remote_name(namespace.name)
    url = validate_remote_url(namespace.url)
    token = _non_empty_token(namespace.token)
    manifest = fetch_manifest(url, token=token) if token is not None else None
    save_remote(RemoteConfig(name=name, url=url, token=token, manifest=manifest))
    if namespace.as_json:
        print_json({"ok": True, "remote": {"name": name, "url": url}})
    else:
        print(f"Connected remote {name}: {url}")
    return 0


def _login_remote(namespace: argparse.Namespace) -> int:
    remote = get_remote(namespace.name)
    token = _non_empty_token(namespace.token)
    if token is None:
        raise CLIUsageError("--token is required")
    manifest = fetch_manifest(remote.url, token=token)
    save_remote(
        RemoteConfig(
            name=remote.name,
            url=remote.url,
            token=token,
            manifest=manifest,
        )
    )
    if namespace.as_json:
        print_json({"ok": True, "remote": {"name": remote.name, "url": remote.url}})
    else:
        print(f"Logged in to {remote.name}")
    return 0


def _list_remotes(namespace: argparse.Namespace) -> int:
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


def _remote_actions(namespace: argparse.Namespace) -> int:
    remote = get_remote(namespace.remote_name)
    manifest = _remote_manifest(remote, token_override=namespace.token)
    if namespace.actions_command == "list":
        actions = _manifest_actions(manifest)
        print_action_summary_list(
            actions,
            as_json=namespace.as_json,
            empty_message="No remote actions are registered.",
        )
        return 0

    if namespace.actions_command == "search":
        actions = _manifest_actions(manifest)
        matches = filter_action_summaries(actions, namespace.query)
        print_action_summary_list(
            matches,
            as_json=namespace.as_json,
            empty_message="No matching remote actions.",
        )
        return 0

    if namespace.actions_command == "describe":
        action = _manifest_action(manifest, namespace.action_name)
        print_action_summary_detail(
            action,
            as_json=namespace.as_json,
            remote_name=remote.name,
        )
        return 0

    _unreachable()


def _remote_call(namespace: argparse.Namespace, unknown: Sequence[str]) -> int:
    remote_name, action_name = namespace.target
    remote = get_remote(remote_name)
    arguments = parse_action_arguments(unknown)
    token = _non_empty_token(namespace.token) if namespace.token is not None else None
    approval_token = _non_empty_approval(namespace.approval)
    response = call_action(
        remote.url,
        token=token or remote.token,
        action=action_name,
        arguments=arguments,
        dry_run=namespace.dry_run,
        approval_token=approval_token,
    )
    print_json(response.body)
    ok = response.status_code < 400 and response.body.get("ok") is not False
    return 0 if ok else 1


def _remote_manifest(
    remote: RemoteConfig,
    *,
    token_override: str | None,
) -> dict[str, object]:
    token = (
        _non_empty_token(token_override) if token_override is not None else remote.token
    )
    manifest = fetch_manifest(remote.url, token=token)
    save_remote(
        RemoteConfig(
            name=remote.name,
            url=remote.url,
            token=remote.token,
            manifest=manifest,
        )
    )
    return manifest


def _manifest_actions(manifest: dict[str, object]) -> list[dict[str, object]]:
    actions = manifest.get("actions")
    if not isinstance(actions, list):
        raise CLIUsageError("Remote manifest is invalid")

    validated: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, dict) or not _is_action_summary(action):
            raise CLIUsageError("Remote manifest is invalid")
        validated.append(action)
    return validated


def _manifest_action(
    manifest: dict[str, object],
    action_name: str,
) -> dict[str, object]:
    for action in _manifest_actions(manifest):
        if action["name"] == action_name:
            return action
    raise CLIUsageError("Unknown remote action")


def _is_action_summary(value: dict[object, object]) -> bool:
    return (
        isinstance(value.get("name"), str)
        and isinstance(value.get("description"), str)
        and isinstance(value.get("method"), str)
        and isinstance(value.get("path"), str)
        and isinstance(value.get("needs_approval"), bool)
        and isinstance(value.get("input_schema"), dict)
    )


def _non_empty_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        raise CLIUsageError("Token must not be empty")
    return token


def _non_empty_approval(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        raise CLIUsageError("Approval token must not be empty")
    return token


async def _authenticate_actions_request(
    app: object,
    headers: dict[str, str],
) -> None:
    from quater.app import Quater

    if not isinstance(app, Quater):
        raise CLIUsageError("Loaded object is not a Quater application")
    if app.cli_auth is None:
        return
    request = Request(
        method="GET",
        path=ACTIONS_RPC_PATH,
        headers=headers,
        context=RequestContext(source="cli", entrypoint="local"),
    )
    await authenticate_request(app.cli_auth, request)


def _get_cli_action(action: ActionDefinition | None) -> ActionDefinition:
    if action is None or not action.cli:
        raise CLIUsageError("Unknown CLI action")
    return action


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quater")
    parser.add_argument("--app", help="Application import path, for example app:app")
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--token", help="Bearer token for the app's cli_auth hook")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Additional auth/header value as 'Name: value'",
    )

    subcommands = parser.add_subparsers(dest="command", required=True)

    dev = subcommands.add_parser("dev")
    _add_server_options(
        dev,
        environment="development",
        reload_default=True,
        log_level_default="debug",
    )

    run = subcommands.add_parser("run")
    _add_server_options(
        run,
        environment="production",
        reload_default=False,
        log_level_default="info",
    )
    run.add_argument(
        "--allow-insecure",
        action="store_true",
        help="Skip production safety checks.",
    )

    connect = subcommands.add_parser("connect")
    connect.add_argument("name")
    connect.add_argument("url")
    connect.add_argument("--token")

    login = subcommands.add_parser("login")
    login.add_argument("name")
    login.add_argument("--token", required=True)

    remotes = subcommands.add_parser("remotes")
    remotes_subcommands = remotes.add_subparsers(
        dest="remotes_command",
        required=True,
    )
    remotes_subcommands.add_parser("list")

    actions = subcommands.add_parser("actions")
    actions_subcommands = actions.add_subparsers(
        dest="actions_command",
        required=True,
    )
    list_actions = actions_subcommands.add_parser("list")
    list_actions.add_argument("remote_name", nargs="?")
    search = actions_subcommands.add_parser("search")
    search.add_argument("remote_name", nargs="?")
    search.add_argument("query")
    describe = actions_subcommands.add_parser("describe")
    describe.add_argument("remote_name", nargs="?")
    describe.add_argument("action_name")

    call = subcommands.add_parser("call")
    call.add_argument("target", nargs="+")
    call.add_argument("--dry-run", action="store_true")
    call.add_argument("--approval")

    return parser


def _add_server_options(
    parser: argparse.ArgumentParser,
    *,
    environment: ServerEnvironment,
    reload_default: bool,
    log_level_default: ServerLogLevel,
) -> None:
    parser.set_defaults(server_environment=environment)
    parser.add_argument(
        "target",
        nargs="?",
        help="Application file/module. Defaults to auto-discovery.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--interface",
        choices=("rsgi", "asgi", "wsgi"),
        default="rsgi",
    )
    parser.add_argument(
        "--loop",
        choices=("auto", "asyncio", "rloop", "uvloop", "winloop"),
        default="auto",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--reload",
        action=argparse.BooleanOptionalAction,
        default=reload_default,
    )
    parser.add_argument(
        "--access-log",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug"),
        default=log_level_default,
    )
    parser.add_argument("--factory", action="store_true")
    parser.add_argument("--working-dir", type=Path)


def _server_options(namespace: argparse.Namespace) -> ServerOptions:
    environment = cast(ServerEnvironment, namespace.server_environment)
    return ServerOptions(
        target=namespace.target,
        environment=environment,
        host=namespace.host,
        port=namespace.port,
        interface=cast(ServerInterface, namespace.interface),
        loop=cast(ServerLoop, namespace.loop),
        workers=namespace.workers,
        reload=namespace.reload,
        access_log=namespace.access_log,
        log_level=cast(ServerLogLevel, namespace.log_level),
        factory=namespace.factory,
        working_dir=namespace.working_dir,
        strict_production=not getattr(namespace, "allow_insecure", False),
    )


def _unreachable() -> NoReturn:
    raise AssertionError("unreachable")
