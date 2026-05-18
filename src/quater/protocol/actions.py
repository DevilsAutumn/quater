"""Protocol helpers for Quater action discovery and execution."""

from __future__ import annotations

from quater.actions.executor import ActionPreflightResult
from quater.actions.registry import ActionDefinition, ActionRegistry
from quater.response import Response, StreamResponse

ACTIONS_PROTOCOL = "quater-actions.v1"
ACTIONS_MANIFEST_PATH = "/.well-known/quater-actions.json"
ACTIONS_RPC_PATH = "/__quater__/actions/call"
MAX_ACTION_RESPONSE_BYTES = 1024 * 1024


def action_manifest(
    registry: ActionRegistry,
    *,
    service_name: str,
    service_version: str,
) -> dict[str, object]:
    return {
        "protocol": ACTIONS_PROTOCOL,
        "service": {
            "name": service_name,
            "version": service_version,
        },
        "rpc": {
            "method": "POST",
            "path": ACTIONS_RPC_PATH,
        },
        "auth": {
            "schemes": [{"type": "bearer"}],
        },
        "actions": [
            action_summary(action)
            for action in sorted(registry.cli_actions(), key=lambda item: item.name)
        ],
    }


def action_summary(action: ActionDefinition) -> dict[str, object]:
    return {
        "name": action.name,
        "description": action.description,
        "method": action.route.method,
        "path": action.route.path,
        "needs_approval": action.needs_approval,
        "input_schema": action.input_schema,
    }


def preflight_payload(result: ActionPreflightResult) -> dict[str, object]:
    return {
        "ok": True,
        "dry_run": True,
        "action": result.action,
        "source": result.source,
        "entrypoint": result.entrypoint,
        "method": result.method,
        "path": result.path,
        "arguments_hash": result.arguments_hash,
        "needs_approval": result.needs_approval,
        "approval_required": result.approval_required,
        "approval_token_provided": result.approval_token_provided,
        "subject": result.subject,
    }


async def response_payload(
    response: Response,
    *,
    max_response_size: int = MAX_ACTION_RESPONSE_BYTES,
) -> dict[str, object]:
    body = await response_body(response, max_response_size=max_response_size)
    return {
        "ok": response.status_code < 400,
        "status_code": response.status_code,
        "body": json_or_text(response, body),
    }


async def response_body(
    response: Response,
    *,
    max_response_size: int = MAX_ACTION_RESPONSE_BYTES,
) -> bytes:
    if not isinstance(response, StreamResponse):
        if len(response.body) > max_response_size:
            raise ValueError(_response_limit_message(max_response_size))
        return response.body

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.body_iterator:
        size += len(chunk)
        if size > max_response_size:
            raise ValueError(_response_limit_message(max_response_size))
        chunks.append(chunk)
    return b"".join(chunks)


def _response_limit_message(max_response_size: int) -> str:
    if max_response_size == MAX_ACTION_RESPONSE_BYTES:
        return "Action response exceeded 1 MiB"
    return "Action response exceeded configured response limit"


def json_or_text(response: Response, body: bytes) -> object:
    content_type = dict(response.headers).get("content-type", "")
    if body and content_type.startswith("application/json"):
        try:
            from quater.serialization import loads_json

            return loads_json(body)
        except Exception:
            return body.decode("utf-8", errors="replace")
    return body.decode("utf-8", errors="replace")
