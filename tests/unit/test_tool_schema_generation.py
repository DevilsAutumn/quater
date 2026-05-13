from __future__ import annotations

import msgspec

from quater import Body, Header, Path, Quater, Query
from quater.tools.registry import build_tool_registry
from quater.typing import AuthContext, AuthRequest


def require_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


class CancelReason(msgspec.Struct):
    reason: str
    notify: bool = False


UPDATE_PAYLOAD = Body(description="Update payload.")
CREATE_ORDER_BODY = Body(alias="order", description="Order payload.")


async def allow_mcp_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="mcp")


def test_tool_schema_includes_path_query_and_body_parameters() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.post(
        "/orders/{id:int}/cancel",
        tool=True,
        description="Cancel an order.",
    )
    async def cancel_order(
        id: int,
        dry_run: bool = False,
        payload: CancelReason | None = None,
    ) -> dict[str, object]:
        return {"id": id, "dry_run": dry_run, "payload": payload}

    registry = build_tool_registry(app.routes)
    schema = registry.tools["cancel_order"].input_schema
    properties = require_object(schema["properties"])
    payload_schema = require_object(properties["payload"])

    assert schema["required"] == ["id"]
    assert properties["id"] == {"type": "integer"}
    assert properties["dry_run"] == {"type": "boolean", "default": False}
    assert payload_schema == {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "notify": {"type": "boolean"},
        },
        "additionalProperties": False,
        "required": ["reason"],
        "default": None,
    }


def test_tool_list_payload_uses_generated_input_schema() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int, include_email: bool = False) -> dict[str, object]:
        return {"id": id, "include_email": include_email}

    registry = build_tool_registry(app.routes)

    assert registry.list_tools() == [
        {
            "name": "get_user",
            "description": "Fetch one user.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "include_email": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
                "required": ["id"],
            },
        }
    ]


def test_tool_schema_uses_handler_names_with_marker_metadata() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.post("/orders/{id}", tool=True, description="Update one order.")
    async def update_order(
        order_id: str = Path(alias="id", description="Order id."),
        include_events: bool = Query(
            default=False,
            alias="include-events",
            description="Include event history.",
        ),
        request_id: str | None = Header(
            default=None,
            alias="X-Request-ID",
            description="Caller request id.",
        ),
        payload: CancelReason = UPDATE_PAYLOAD,
    ) -> dict[str, object]:
        return {
            "order_id": order_id,
            "include_events": include_events,
            "request_id": request_id,
            "payload": payload,
        }

    registry = build_tool_registry(app.routes)
    schema = registry.tools["update_order"].input_schema

    assert schema["properties"] == {
        "order_id": {
            "type": "string",
            "description": "Order id.",
        },
        "include_events": {
            "type": "boolean",
            "description": "Include event history.",
            "default": False,
        },
        "request_id": {
            "type": "string",
            "description": "Caller request id.",
            "default": None,
        },
        "payload": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "notify": {"type": "boolean"},
            },
            "additionalProperties": False,
            "required": ["reason"],
            "description": "Update payload.",
        },
    }
    assert schema["required"] == ["order_id", "payload"]


def test_body_alias_changes_action_argument_name() -> None:
    app = Quater(mcp_auth=allow_mcp_auth)

    @app.post("/orders", tool=True, description="Create one order.")
    async def create_order(
        payload: CancelReason = CREATE_ORDER_BODY,
    ) -> dict[str, object]:
        return {"payload": payload}

    registry = build_tool_registry(app.routes)
    schema = registry.tools["create_order"].input_schema

    assert schema["properties"] == {
        "order": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "notify": {"type": "boolean"},
            },
            "additionalProperties": False,
            "required": ["reason"],
            "description": "Order payload.",
        }
    }
    assert schema["required"] == ["order"]
