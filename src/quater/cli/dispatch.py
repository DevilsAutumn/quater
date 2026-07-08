from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from typing import cast

from quater.cli.apps import load_app
from quater.cli.errors import CLIUsageError
from quater.cli.local import run_local_actions, run_local_call
from quater.cli.parser import _build_parser
from quater.cli.parsing import parse_headers
from quater.cli.remote import (
    connect_remote,
    list_remotes,
    login_remote,
    remote_actions,
    remote_call,
)
from quater.cli.server import (
    ServerEnvironment,
    ServerInterface,
    ServerLogLevel,
    ServerLoop,
    ServerOptions,
)
from quater.cli.utils import _local_cli_token


def build_parser() -> argparse.ArgumentParser:
    return _build_parser()


async def run(namespace: argparse.Namespace, unknown: Sequence[str]) -> int:
    if namespace.command in {"dev", "run"}:
        _serve(_server_options(namespace))
        return 0
    if namespace.command == "connect":
        return connect_remote(namespace)
    if namespace.command == "login":
        return login_remote(namespace)
    if namespace.command == "remotes":
        return list_remotes(namespace)

    if namespace.command == "actions" and getattr(namespace, "remote_name", None):
        return remote_actions(namespace)
    if namespace.command == "call" and len(namespace.target) == 2:
        return remote_call(namespace, unknown)

    app_path = namespace.app or os.environ.get("QUATER_APP")
    if app_path is None:
        raise CLIUsageError("--app is required unless QUATER_APP is set")

    app = load_app(app_path)
    headers = parse_headers(token=_local_cli_token(namespace), headers=namespace.header)
    if namespace.command == "actions":
        return await run_local_actions(namespace, app, headers)
    if namespace.command == "call":
        return await run_local_call(namespace, app, headers, list(unknown))

    raise CLIUsageError("unreachable")


def _serve(options: ServerOptions) -> None:
    from quater.cli.main import serve as main_serve

    main_serve(options)


def _server_options(namespace: argparse.Namespace) -> ServerOptions:
    environment = cast(ServerEnvironment, namespace.server_environment)
    target = namespace.target or namespace.app or os.environ.get("QUATER_APP")
    return ServerOptions(
        target=target,
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
