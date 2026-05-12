"""Tool description validation."""

from __future__ import annotations

from quater.actions.descriptions import (
    MAX_ACTION_DESCRIPTION_LENGTH,
    handler_action_description,
    normalize_action_description,
    resolve_action_description,
)

MAX_TOOL_DESCRIPTION_LENGTH = MAX_ACTION_DESCRIPTION_LENGTH


def normalize_route_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def normalize_tool_description(value: str | None) -> str | None:
    return normalize_action_description(value)


def handler_tool_description(handler: object) -> str | None:
    return handler_action_description(handler)


def resolve_tool_description(
    route_name: str,
    explicit_description: str | None,
    handler: object,
) -> str:
    return resolve_action_description(
        "Tool route",
        route_name,
        explicit_description,
        handler,
    )
