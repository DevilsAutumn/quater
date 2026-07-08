from __future__ import annotations

import argparse
from pathlib import Path

from quater.cli.server import (
    ServerEnvironment,
    ServerLogLevel,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quater")
    parser.add_argument("--app", help="Application import path, for example app:app")
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument(
        "--token",
        help=(
            "Bearer token for the app's cli-surface authenticator. "
            "Local actions also read QUATER_TOKEN."
        ),
    )
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
