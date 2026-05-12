"""Description validation shared by externally callable actions."""

from __future__ import annotations

from quater.exceptions import ConfigurationError

MAX_ACTION_DESCRIPTION_LENGTH = 1000


def normalize_action_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_ACTION_DESCRIPTION_LENGTH:
        raise ConfigurationError("Action descriptions must be 1000 characters or fewer")
    return normalized


def handler_action_description(handler: object) -> str | None:
    doc = getattr(handler, "__doc__", None)
    if not isinstance(doc, str):
        return None
    first_line = doc.strip().splitlines()[0] if doc.strip() else ""
    return normalize_action_description(first_line)


def resolve_action_description(
    kind: str,
    action_name: str,
    explicit_description: str | None,
    handler: object,
) -> str:
    description = normalize_action_description(explicit_description)
    if description is not None:
        return description

    description = handler_action_description(handler)
    if description is not None:
        return description

    raise ConfigurationError(
        f"{kind} {action_name!r} must define a non-empty description"
    )
