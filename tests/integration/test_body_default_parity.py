from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from quater import AuthConfig, Body, Quater, Request
from quater.actions.executor import execute_action
from quater.actions.registry import ActionDefinition, build_action_registry
from quater.exceptions import BadRequestError
from quater.typing import AuthContext


async def allow_action_auth(ctx: Request) -> AuthContext | None:
    return AuthContext(subject=ctx.context.source)


DEFAULT_BODY = Body({"x": 7})
OPTIONAL_DEFAULT_BODY = Body({"x": 7})
OPTIONAL_BODY = Body()
REQUIRED_BODY = Body()
ANY_BODY = Body()


def action_for(app: Quater, name: str) -> ActionDefinition:
    action = build_action_registry(app.routes).get(name)
    assert action is not None
    return action


async def mcp_call(
    app: Quater,
    *,
    name: str,
    arguments: Mapping[str, object],
) -> tuple[int, dict[str, object]]:
    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={
                "authorization": "Bearer mcp",
                "content-type": "application/json",
            },
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": dict(arguments)},
                }
            ).encode("utf-8"),
        )
    )
    return response.status_code, json.loads(response.body)


def mcp_text(payload: Mapping[str, object]) -> str:
    result = payload["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    item = content[0]
    assert isinstance(item, dict)
    text = item["text"]
    assert isinstance(text, str)
    return text


def body_default_app() -> Quater:
    app = Quater(auth=[AuthConfig(allow_action_auth, surfaces=["mcp", "cli"])])

    @app.post("/items", tool=True, cli=True, description="Create item.")
    async def create_item(
        payload: dict[str, int] = DEFAULT_BODY,
    ) -> dict[str, int]:
        return payload

    return app


def optional_body_app() -> Quater:
    app = Quater(auth=[AuthConfig(allow_action_auth, surfaces=["mcp", "cli"])])

    @app.post("/items", tool=True, cli=True, description="Create item.")
    async def create_item(
        payload: dict[str, int] | None = OPTIONAL_BODY,
    ) -> dict[str, object]:
        return {"payload": payload}

    return app


def optional_body_with_default_app() -> Quater:
    app = Quater(auth=[AuthConfig(allow_action_auth, surfaces=["mcp", "cli"])])

    @app.post("/items", tool=True, cli=True, description="Create item.")
    async def create_item(
        payload: dict[str, int] | None = OPTIONAL_DEFAULT_BODY,
    ) -> dict[str, object]:
        return {"payload": payload}

    return app


@pytest.mark.asyncio
async def test_missing_default_body_matches_http_mcp_and_cli() -> None:
    app = body_default_app()

    http_response = await app.handle(Request(method="POST", path="/items"))
    assert http_response.status_code == 200
    assert http_response.body == b'{"x":7}'

    mcp_status, mcp_payload = await mcp_call(app, name="create_item", arguments={})
    assert mcp_status == 200
    assert mcp_text(mcp_payload) == '{"x":7}'

    cli_response = await execute_action(
        action_for(app, "create_item"),
        Request(
            method="POST",
            path="/__quater__/actions/call",
            auth=AuthContext(subject="cli"),
        ),
        {},
        source="cli",
    )
    assert cli_response.status_code == 200
    assert cli_response.body == b'{"x":7}'


@pytest.mark.asyncio
async def test_missing_optional_body_matches_http_mcp_and_cli() -> None:
    app = optional_body_app()

    http_response = await app.handle(Request(method="POST", path="/items"))
    assert http_response.status_code == 200
    assert http_response.body == b'{"payload":null}'

    mcp_status, mcp_payload = await mcp_call(app, name="create_item", arguments={})
    assert mcp_status == 200
    assert mcp_text(mcp_payload) == '{"payload":null}'

    cli_response = await execute_action(
        action_for(app, "create_item"),
        Request(
            method="POST",
            path="/__quater__/actions/call",
            auth=AuthContext(subject="cli"),
        ),
        {},
        source="cli",
    )
    assert cli_response.status_code == 200
    assert cli_response.body == b'{"payload":null}'


@pytest.mark.asyncio
async def test_default_body_wins_over_optional_when_body_is_missing() -> None:
    app = optional_body_with_default_app()

    http_response = await app.handle(Request(method="POST", path="/items"))
    assert http_response.status_code == 200
    assert http_response.body == b'{"payload":{"x":7}}'

    mcp_status, mcp_payload = await mcp_call(app, name="create_item", arguments={})
    assert mcp_status == 200
    assert mcp_text(mcp_payload) == '{"payload":{"x":7}}'

    cli_response = await execute_action(
        action_for(app, "create_item"),
        Request(
            method="POST",
            path="/__quater__/actions/call",
            auth=AuthContext(subject="cli"),
        ),
        {},
        source="cli",
    )
    assert cli_response.status_code == 200
    assert cli_response.body == b'{"payload":{"x":7}}'


@pytest.mark.asyncio
async def test_required_body_empty_http_request_is_missing_not_malformed() -> None:
    app = Quater()

    @app.post("/items")
    async def create_item(payload: dict[str, int] = REQUIRED_BODY) -> dict[str, int]:
        return payload

    response = await app.handle(Request(method="POST", path="/items"))

    assert response.status_code == 400
    assert response.body == b"Missing required body parameter: payload"


@pytest.mark.asyncio
async def test_default_body_does_not_hide_non_empty_malformed_json() -> None:
    app = body_default_app()

    response = await app.handle(Request(method="POST", path="/items", body=b'{"x":'))

    assert response.status_code == 400
    assert response.body == b"Malformed JSON body"


@pytest.mark.asyncio
async def test_whitespace_only_body_is_malformed_json_not_missing() -> None:
    app = body_default_app()

    response = await app.handle(Request(method="POST", path="/items", body=b" \n\t"))

    assert response.status_code == 400
    assert response.body == b"Malformed JSON body"


@pytest.mark.asyncio
async def test_any_body_still_accepts_arbitrary_json_values() -> None:
    app = Quater()

    @app.post("/echo")
    async def echo(payload: Any = ANY_BODY) -> object:
        return payload

    response = await app.handle(
        Request(method="POST", path="/echo", body=b'[1,"two",null]')
    )

    assert response.status_code == 200
    assert response.body == b'[1,"two",null]'


@pytest.mark.asyncio
async def test_json_null_is_input_not_a_missing_body() -> None:
    optional_app = optional_body_app()
    optional_response = await optional_app.handle(
        Request(method="POST", path="/items", body=b"null")
    )

    assert optional_response.status_code == 200
    assert optional_response.body == b'{"payload":null}'

    required_app = Quater()

    @required_app.post("/items")
    async def create_item(payload: dict[str, int] = REQUIRED_BODY) -> dict[str, int]:
        return payload

    required_response = await required_app.handle(
        Request(method="POST", path="/items", body=b"null")
    )

    assert required_response.status_code == 400
    assert required_response.body == b"Invalid JSON body for parameter: payload"


@pytest.mark.asyncio
async def test_explicit_null_does_not_use_default_body_across_surfaces() -> None:
    app = body_default_app()

    http_response = await app.handle(
        Request(method="POST", path="/items", body=b"null")
    )
    assert http_response.status_code == 400
    assert http_response.body == b"Invalid JSON body for parameter: payload"

    mcp_status, mcp_payload = await mcp_call(
        app,
        name="create_item",
        arguments={"payload": None},
    )
    assert mcp_status == 200
    assert mcp_payload["error"] == {
        "code": -32602,
        "message": "Invalid JSON body for parameter: payload",
    }

    with pytest.raises(BadRequestError, match="Invalid JSON body for parameter"):
        await execute_action(
            action_for(app, "create_item"),
            Request(
                method="POST",
                path="/__quater__/actions/call",
                auth=AuthContext(subject="cli"),
            ),
            {"payload": None},
            source="cli",
        )
