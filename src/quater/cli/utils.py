from __future__ import annotations

import argparse
import os
from typing import NoReturn, cast

from quater.cli.errors import CLIUsageError


def _non_empty_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        raise CLIUsageError("Token must not be empty")
    return token


def _local_cli_token(namespace: argparse.Namespace) -> str | None:
    if namespace.token is not None:
        return cast(str, namespace.token)
    return os.environ.get("QUATER_TOKEN")


def _non_empty_approval(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        raise CLIUsageError("Approval token must not be empty")
    return token


def _unreachable() -> NoReturn:
    raise AssertionError("unreachable")
