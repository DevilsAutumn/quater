from __future__ import annotations

import argparse

from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition
from quater.app import Quater
from quater.cli.errors import CLIUsageError
from quater.cli.output import (
    action_summaries,
    filter_action_summaries,
    print_action_detail,
    print_action_summary_list,
    print_preflight,
    print_response,
)
from quater.cli.utils import _non_empty_approval, _unreachable
from quater.protocol.actions import ACTIONS_RPC_PATH
from quater.request import Request
from quater.typing import RequestContext


async def run_local_actions(
    namespace: argparse.Namespace,
    app: Quater,
    headers: dict[str, str],
) -> int:
    await _authenticate_actions_request(app, headers)
    registry = app._compiled_action_registry()
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
        action = get_cli_action(registry.get(namespace.action_name))
        print_action_detail(action, as_json=namespace.as_json)
        return 0
    _unreachable()


async def run_local_call(
    namespace: argparse.Namespace,
    app: Quater,
    headers: dict[str, str],
    unknown: tuple[str, ...] | list[str],
) -> int:
    if len(namespace.target) != 1:
        raise CLIUsageError("Local calls must specify exactly one action")
    registry = app._compiled_action_registry()
    action = get_cli_action(registry.get(namespace.target[0]))
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
        app=app,
    )
    approval_token = _non_empty_approval(namespace.approval)
    try:
        await app._authenticate_surface(
            "cli",
            request,
            public=action.route.public,
        )
        if namespace.dry_run:
            result = await preflight_action(
                action,
                request,
                arguments,
                source="cli",
                approval_token=approval_token,
            )
            print_preflight(result, as_json=namespace.as_json)
            return 0

        response = await execute_action(
            action,
            request,
            arguments,
            source="cli",
            global_stack=app._middleware,
            approval_hook=app.action_approval,
            approval_token=approval_token,
            debug=app.config.debug,
        )
        return await print_response(response, as_json=namespace.as_json)
    finally:
        await request._aclose_resources()


async def _authenticate_actions_request(
    app: Quater,
    headers: dict[str, str],
) -> None:

    if not isinstance(app, Quater):
        raise CLIUsageError("Loaded object is not a Quater application")
    request = Request(
        method="GET",
        path=ACTIONS_RPC_PATH,
        headers=headers,
        context=RequestContext(source="cli", entrypoint="local"),
        app=app,
    )
    try:
        await app._authenticate_surface("cli", request, public=())
    finally:
        await request._aclose_resources()


def get_cli_action(action: ActionDefinition | None) -> ActionDefinition:
    if action is None or not action.cli:
        raise CLIUsageError("Unknown CLI action")
    return action


def parse_action_arguments(unknown: tuple[str, ...] | list[str]) -> dict[str, object]:
    from quater.cli.parsing import parse_action_arguments as _parse_action_arguments

    return _parse_action_arguments(unknown)
