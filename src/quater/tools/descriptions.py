"""Tool description validation."""

from __future__ import annotations

from quater.actions.descriptions import resolve_action_description


def normalize_route_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
