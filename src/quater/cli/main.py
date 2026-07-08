"""Command line entrypoint for Quater."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from quater.cli.client import (
    RemoteResponse,
)
from quater.cli.client import (
    call_action as _call_action,
)
from quater.cli.client import (
    fetch_manifest as _fetch_manifest,
)
from quater.cli.dispatch import run as _dispatch_run
from quater.cli.errors import CLIError
from quater.cli.parser import _build_parser
from quater.cli.remote import (
    connect_remote as _connect_remote_impl,
)
from quater.cli.remote import (
    list_remotes as _list_remotes_impl,
)
from quater.cli.remote import (
    login_remote as _login_remote_impl,
)
from quater.cli.remote import (
    remote_actions as _remote_actions_impl,
)
from quater.cli.remote import (
    remote_call as _remote_call_impl,
)
from quater.cli.server import (
    ServerOptions,
)
from quater.cli.server import (
    serve as _serve_impl,
)
from quater.exceptions import HTTPError, QuaterError


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
    return await _dispatch_run(namespace, unknown)


def fetch_manifest(base_url: str, *, token: str | None) -> dict[str, object]:
    return _fetch_manifest(
        base_url,
        token=token,
    )


def call_action(
    base_url: str,
    *,
    token: str | None,
    action: str,
    arguments: dict[str, object],
    dry_run: bool,
    approval_token: str | None,
) -> RemoteResponse:
    return _call_action(
        base_url,
        token=token,
        action=action,
        arguments=arguments,
        dry_run=dry_run,
        approval_token=approval_token,
    )


def serve(options: ServerOptions) -> None:
    _serve_impl(options)


def _connect_remote(namespace: argparse.Namespace) -> int:
    return _connect_remote_impl(namespace)


def _login_remote(namespace: argparse.Namespace) -> int:
    return _login_remote_impl(namespace)


def _list_remotes(namespace: argparse.Namespace) -> int:
    return _list_remotes_impl(namespace)


def _remote_actions(namespace: argparse.Namespace) -> int:
    return _remote_actions_impl(namespace)


def _remote_call(namespace: argparse.Namespace, unknown: Sequence[str]) -> int:
    return _remote_call_impl(namespace, unknown)
