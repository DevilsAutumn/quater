"""Approval checks for actions that can mutate state outside normal HTTP calls."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from quater.exceptions import BadRequestError
from quater.typing import ActionApproval, ApprovalRequest, AuthContext, RequestContext


class ApprovalRequiredError(Exception):
    """Raised when an action needs an approval token before execution."""

    def __init__(self, action: str, arguments_hash: str) -> None:
        self.action = action
        self.arguments_hash = arguments_hash
        super().__init__("Approval required")


class ApprovalDeniedError(Exception):
    """Raised when an approval hook rejects a token."""

    def __init__(self, action: str, arguments_hash: str) -> None:
        self.action = action
        self.arguments_hash = arguments_hash
        super().__init__("Approval denied")


async def require_action_approval(
    approval: ActionApproval | None,
    *,
    action: str,
    arguments: Mapping[str, object],
    token: str | None,
    auth: AuthContext | None,
    context: RequestContext,
) -> None:
    arguments_hash = action_arguments_hash(action, arguments)
    if token is None:
        raise ApprovalRequiredError(action, arguments_hash)
    if approval is None:
        raise ApprovalDeniedError(action, arguments_hash)

    approved = await approval(
        ApprovalRequest(
            action=action,
            arguments_hash=arguments_hash,
            token=token,
            auth=auth,
            context=context,
        )
    )
    if not approved:
        raise ApprovalDeniedError(action, arguments_hash)


def action_arguments_hash(action: str, arguments: Mapping[str, object]) -> str:
    payload = {
        "action": action,
        "arguments": _canonical_value(arguments),
    }
    try:
        from quater.serialization import dumps_json

        encoded = dumps_json(payload)
    except (TypeError, ValueError) as exc:
        raise BadRequestError("Invalid action arguments") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise BadRequestError("Invalid action arguments")
            items.append((key, _canonical_value(item)))
        return {key: item for key, item in sorted(items, key=lambda entry: entry[0])}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_canonical_value(item) for item in value]
    return value
