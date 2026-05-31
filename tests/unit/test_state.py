from __future__ import annotations

import asyncio
import json

import pytest

from quater import (
    AuthConfig,
    AuthContext,
    Header,
    Quater,
    Request,
    Response,
    TestClient,
)
from quater.actions.executor import execute_action
from quater.actions.registry import build_action_registry
from quater.protocol.actions import ACTIONS_RPC_PATH


async def allow_auth(ctx: Request) -> AuthContext | None:
    return AuthContext(subject=ctx.context.source)


@pytest.mark.asyncio
async def test_request_created_directly_has_empty_request_state() -> None:
    first = Request(method="GET", path="/one")
    second = Request(method="GET", path="/two")

    first.state.trace_id = "req-1"

    assert first.app is None
    assert second.app is None
    assert first.state.trace_id == "req-1"
    assert not hasattr(second.state, "trace_id")


def test_request_state_is_lazy_and_stable() -> None:
    request = Request(method="GET", path="/lazy")

    assert request._state is None

    state = request.state

    assert request._state is state
    assert request.state is state


@pytest.mark.asyncio
async def test_handler_can_read_application_state_from_request() -> None:
    app = Quater()
    app.state.service_name = "orders"

    @app.get("/service")
    async def service(request: Request) -> dict[str, object]:
        assert request.app is app
        return {"service": request.app.state.service_name}

    response = await app.handle(Request(method="GET", path="/service"))

    assert json.loads(response.body) == {"service": "orders"}


@pytest.mark.asyncio
async def test_app_handle_overwrites_a_prebound_request_app() -> None:
    old_app = Quater()
    app = Quater()

    @app.get("/current")
    async def current(request: Request) -> dict[str, object]:
        assert request.app is app
        return {"current": True}

    request = Request(method="GET", path="/current", app=old_app)

    response = await app.handle(request)

    assert request.app is app
    assert json.loads(response.body) == {"current": True}


@pytest.mark.asyncio
async def test_application_state_is_isolated_between_app_instances() -> None:
    first_app = Quater()
    second_app = Quater()
    first_app.state.name = "first"
    second_app.state.name = "second"

    @first_app.get("/name")
    async def first_name(request: Request) -> dict[str, object]:
        assert request.app is first_app
        return {"name": request.app.state.name}

    @second_app.get("/name")
    async def second_name(request: Request) -> dict[str, object]:
        assert request.app is second_app
        return {"name": request.app.state.name}

    first_response, second_response = await asyncio.gather(
        first_app.handle(Request(method="GET", path="/name")),
        second_app.handle(Request(method="GET", path="/name")),
    )

    assert json.loads(first_response.body) == {"name": "first"}
    assert json.loads(second_response.body) == {"name": "second"}


@pytest.mark.asyncio
async def test_request_state_is_available_to_middleware_and_handler() -> None:
    app = Quater()

    @app.before_request
    async def add_trace(request: Request) -> Response | None:
        request.state.trace_id = "req-1"
        return None

    @app.get("/trace")
    async def trace(request: Request) -> dict[str, object]:
        return {"trace_id": request.state.trace_id}

    response = await app.handle(Request(method="GET", path="/trace"))

    assert json.loads(response.body) == {"trace_id": "req-1"}


@pytest.mark.asyncio
async def test_request_state_is_isolated_between_concurrent_requests() -> None:
    app = Quater()

    @app.before_request
    async def store_value(request: Request) -> Response | None:
        request.state.value = request.query["value"]
        await asyncio.sleep(0)
        return None

    @app.get("/echo")
    async def echo(request: Request) -> dict[str, object]:
        await asyncio.sleep(0)
        return {"value": request.state.value}

    first, second = await asyncio.gather(
        app.handle(Request(method="GET", path="/echo", query_string="value=one")),
        app.handle(Request(method="GET", path="/echo", query_string="value=two")),
    )

    assert json.loads(first.body) == {"value": "one"}
    assert json.loads(second.body) == {"value": "two"}


@pytest.mark.asyncio
async def test_lifespan_hooks_can_share_application_state() -> None:
    app = Quater()

    @app.on_startup
    async def open_resource() -> None:
        app.state.resource = "open"

    @app.on_shutdown
    async def close_resource() -> None:
        assert app.state.resource == "open"
        app.state.resource = "closed"

    await app.startup()
    assert app.state.resource == "open"

    await app.shutdown()
    assert app.state.resource == "closed"


@pytest.mark.asyncio
async def test_mcp_tool_can_read_application_state() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp"])])
    app.state.store_name = "primary"

    @app.get("/store", tool=True, description="Read the configured store name.")
    async def store(request: Request) -> dict[str, object]:
        assert request.app is app
        return {"store": request.app.state.store_name}

    async with TestClient(app) as client:
        response = await client.mcp.tools_call("store", token="secret")

    payload = response.json()

    assert response.status_code == 200
    assert payload["result"] == {
        "content": [{"type": "text", "text": '{"store":"primary"}'}],
        "isError": False,
    }


@pytest.mark.asyncio
async def test_cli_action_request_preserves_application_state() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])
    app.state.store_name = "local"

    @app.get("/store", cli=True, description="Read the configured store name.")
    async def store(request: Request) -> dict[str, object]:
        assert request.app is app
        return {"store": request.app.state.store_name}

    action = build_action_registry(app.routes).get("store")
    assert action is not None

    response = await execute_action(
        action,
        Request(method="POST", path=ACTIONS_RPC_PATH, app=app),
        {},
        source="cli",
    )

    assert json.loads(response.body) == {"store": "local"}


@pytest.mark.asyncio
async def test_cli_action_with_header_preserves_app_and_request_state() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])
    app.state.store_name = "local"

    async def attach_state(request: Request) -> Response | None:
        assert request.app is app
        request.state.marker = request.app.state.store_name
        return None

    @app.get(
        "/store",
        cli=True,
        before=[attach_state],
        description="Read the configured store name.",
    )
    async def store(
        request: Request,
        agent: str = Header(alias="X-Agent"),
    ) -> dict[str, object]:
        assert request.app is app
        return {
            "agent": agent,
            "marker": request.state.marker,
            "store": request.app.state.store_name,
        }

    action = build_action_registry(app.routes).get("store")
    assert action is not None

    response = await execute_action(
        action,
        Request(method="POST", path=ACTIONS_RPC_PATH, app=app),
        {"agent": "ops"},
        source="cli",
    )

    assert json.loads(response.body) == {
        "agent": "ops",
        "marker": "local",
        "store": "local",
    }
