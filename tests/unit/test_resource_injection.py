from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Any, cast

import pytest

from quater import (
    AuthConfig,
    AuthContext,
    JSONResponse,
    Quater,
    Query,
    Request,
    Resource,
    RouteGroup,
    StreamResponse,
    TestClient,
)
from quater._finalize import run_response_finalizers
from quater.actions.executor import execute_action, preflight_action
from quater.actions.registry import ActionDefinition, build_action_registry
from quater.exceptions import BadRequestError, ConfigurationError, RouteBindingError
from quater.tools.registry import build_tool_registry


class FakeSession:
    def __init__(self, label: str) -> None:
        self.label = label


async def allow_auth(ctx: Request) -> AuthContext | None:
    return AuthContext(subject=ctx.context.source)


def action_for(app: Quater, name: str) -> ActionDefinition:
    action = build_action_registry(app.routes).get(name)
    assert action is not None
    return action


@pytest.mark.asyncio
async def test_resource_injection_resolves_and_cleans_up_per_request() -> None:
    events: list[str] = []

    async def session_provider(request: Request) -> AsyncIterator[FakeSession]:
        events.append(f"open:{request.path}")
        try:
            yield FakeSession("primary")
        finally:
            events.append(f"close:{request.path}")

    app = Quater()

    @app.get("/orders", inject={"session": Resource(session_provider)})
    async def list_orders(session: FakeSession) -> dict[str, str]:
        events.append(f"handler:{session.label}")
        return {"session": session.label}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.body == b'{"session":"primary"}'
    assert events == ["open:/orders", "handler:primary", "close:/orders"]


@pytest.mark.asyncio
async def test_resource_cleanup_runs_when_handler_raises() -> None:
    events: list[str] = []

    async def session_provider() -> AsyncIterator[FakeSession]:
        events.append("open")
        try:
            yield FakeSession("primary")
        finally:
            events.append("close")

    app = Quater()

    @app.get("/boom", inject={"session": Resource(session_provider)})
    async def boom(session: FakeSession) -> dict[str, str]:
        raise RuntimeError(session.label)

    response = await app.handle(Request(method="GET", path="/boom"))

    assert response.status_code == 500
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_resource_stays_open_until_streaming_response_is_consumed() -> None:
    events: list[str] = []

    async def provider() -> AsyncIterator[FakeSession]:
        events.append("open")
        try:
            yield FakeSession("primary")
        finally:
            events.append("close")

    app = Quater()

    @app.get("/stream", inject={"session": Resource(provider)})
    async def stream(session: FakeSession) -> StreamResponse:
        async def body() -> AsyncIterator[bytes]:
            events.append(f"chunk:{session.label}")
            yield session.label.encode()

        return StreamResponse(body())

    async with TestClient(app) as client:
        response = await client.get("/stream")

    assert response.body == b"primary"
    assert events == ["open", "chunk:primary", "close"]


@pytest.mark.asyncio
async def test_resource_cleanup_survives_response_replacement_middleware() -> None:
    events: list[str] = []

    async def provider() -> AsyncIterator[FakeSession]:
        events.append("open")
        try:
            yield FakeSession("primary")
        finally:
            events.append("close")

    app = Quater()

    @app.after_response
    async def replace_response(
        request: Request,
        response: object,
    ) -> JSONResponse:
        return JSONResponse({"replaced": request.path == "/orders"})

    @app.get("/orders", inject={"session": Resource(provider)})
    async def list_orders(session: FakeSession) -> dict[str, str]:
        events.append(f"handler:{session.label}")
        return {"session": session.label}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.body == b'{"replaced":true}'
    assert events == ["open", "handler:primary", "close"]


@pytest.mark.asyncio
async def test_same_resource_object_is_resolved_once_per_handler_call() -> None:
    calls = 0

    async def session_provider() -> FakeSession:
        nonlocal calls
        calls += 1
        return FakeSession("primary")

    session = Resource(session_provider)
    app = Quater()

    @app.get("/orders", inject={"read": session, "write": session})
    async def list_orders(read: FakeSession, write: FakeSession) -> dict[str, object]:
        return {"same": read is write, "label": read.label}

    response = await app.handle(Request(method="GET", path="/orders"))

    assert response.body == b'{"same":true,"label":"primary"}'
    assert calls == 1


def test_unused_injection_is_rejected_when_routes_compile() -> None:
    async def provider() -> FakeSession:
        return FakeSession("primary")

    app = Quater()

    @app.get("/orders", inject={"session": Resource(provider)})
    async def list_orders() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RouteBindingError, match="does not exist"):
        app.compile_routes()


def test_injected_parameter_cannot_also_be_bound_from_the_request() -> None:
    async def provider() -> str:
        return "ignored"

    app = Quater()

    @app.get("/orders/{order_id}", inject={"order_id": Resource(provider)})
    async def get_order(order_id: str) -> dict[str, str]:
        return {"id": order_id}

    with pytest.raises(RouteBindingError, match="conflicts with a path parameter"):
        app.compile_routes()


def test_injected_parameter_cannot_use_parameter_markers() -> None:
    async def provider() -> str:
        return "ignored"

    app = Quater()

    @app.get("/orders", inject={"value": Resource(provider)})
    async def list_orders(value: str = Query(default="fallback")) -> dict[str, str]:
        return {"value": value}

    with pytest.raises(RouteBindingError, match="cannot use a parameter marker"):
        app.compile_routes()


def test_route_group_injections_are_inherited_by_routes() -> None:
    async def provider() -> FakeSession:
        return FakeSession("group")

    app = Quater()
    group = RouteGroup(prefix="/orders", inject={"session": Resource(provider)})

    @group.get("/")
    async def list_orders(session: FakeSession) -> dict[str, str]:
        return {"session": session.label}

    app.include(group)
    route = app.routes[0]

    assert "session" in route.inject


def test_resource_rejects_invalid_provider_configuration() -> None:
    def provider() -> FakeSession:
        return FakeSession("primary")

    def uses_varargs(*args: object) -> FakeSession:
        return FakeSession(str(len(args)))

    # Provider parameters that are neither the request nor a resource dependency
    # are rejected when routes compile (see test_resource_dependencies), not at
    # construction — so a provider can carry resource dependencies.
    with pytest.raises(
        ConfigurationError,
        match="scope must be 'function' or 'request'",
    ):
        Resource(provider, scope=cast(Any, "application"))

    with pytest.raises(TypeError, match="provider must be callable"):
        Resource(cast(Any, object()))

    with pytest.raises(ConfigurationError, match=r"\*args or \*\*kwargs"):
        Resource(uses_varargs)


@pytest.mark.asyncio
async def test_resource_provider_receives_request_by_annotation_or_keyword() -> None:
    def annotated(ctx: Request) -> str:
        return f"annotated:{ctx.path}"

    def keyword_only(*, request: Request) -> str:
        return f"keyword:{request.path}"

    def fallback(request: Request) -> str:
        return f"fallback:{request.path}"

    # A bad forward reference should not break providers named "request".
    fallback.__annotations__["request"] = "MissingResourceRequest"

    request = Request(method="GET", path="/orders")
    async with AsyncExitStack() as stack:
        assert await Resource(annotated).resolve(request, stack) == "annotated:/orders"
        assert await Resource(keyword_only).resolve(request, stack) == "keyword:/orders"
        assert await Resource(fallback).resolve(request, stack) == "fallback:/orders"


@pytest.mark.asyncio
async def test_resource_generators_must_yield_exactly_once() -> None:
    def no_yield() -> Iterator[str]:
        if False:
            yield "never"

    def yields_twice() -> Iterator[str]:
        yield "first"
        yield "second"

    async def async_no_yield() -> AsyncIterator[str]:
        if False:
            yield "never"

    async def async_yields_twice() -> AsyncIterator[str]:
        yield "first"
        yield "second"

    request = Request(method="GET", path="/orders")

    async with AsyncExitStack() as stack:
        with pytest.raises(RuntimeError, match="did not yield"):
            await Resource(no_yield, name="empty").resolve(request, stack)

    async with AsyncExitStack() as stack:
        with pytest.raises(RuntimeError, match="did not yield"):
            await Resource(async_no_yield, name="empty").resolve(request, stack)

    stack = AsyncExitStack()
    assert await Resource(yields_twice, name="twice").resolve(request, stack) == "first"
    with pytest.raises(RuntimeError, match="yielded more than once"):
        await stack.aclose()

    stack = AsyncExitStack()
    assert (
        await Resource(async_yields_twice, name="async_twice").resolve(request, stack)
        == "first"
    )
    with pytest.raises(RuntimeError, match="yielded more than once"):
        await stack.aclose()


def test_route_group_rejects_ambiguous_injection_overrides() -> None:
    async def first_provider() -> FakeSession:
        return FakeSession("first")

    async def second_provider() -> FakeSession:
        return FakeSession("second")

    app = Quater()
    group = RouteGroup(prefix="/orders", inject={"session": Resource(first_provider)})

    @group.get("/", inject={"session": Resource(second_provider)})
    async def list_orders(session: FakeSession) -> dict[str, str]:
        return {"session": session.label}

    with pytest.raises(ConfigurationError, match="Duplicate injected parameter"):
        app.include(group)


def test_tool_and_action_schemas_do_not_expose_injected_values() -> None:
    async def provider() -> FakeSession:
        return FakeSession("primary")

    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        inject={"session": Resource(provider)},
        description="Fetch one order.",
    )
    async def get_order(order_id: str, session: FakeSession) -> dict[str, str]:
        return {"id": order_id, "session": session.label}

    tool = build_tool_registry(app.routes).get("get_order")
    assert tool is not None
    assert tool.input_schema["properties"] == {"order_id": {"type": "string"}}

    action = action_for(app, "get_order")
    assert action.input_schema["properties"] == {"order_id": {"type": "string"}}


@pytest.mark.asyncio
async def test_cli_action_resolves_injected_resources_at_execution_time() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def provider(request: Request) -> AsyncIterator[FakeSession]:
        events.append(f"open:{request.context.source}")
        try:
            yield FakeSession("primary")
        finally:
            events.append(f"close:{request.context.source}")

    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get(
        "/orders/{order_id}",
        cli=True,
        inject={"session": Resource(provider)},
        description="Fetch one order.",
    )
    async def get_order(order_id: str, session: FakeSession) -> dict[str, str]:
        return {"id": order_id, "session": session.label}

    result = await preflight_action(
        action_for(app, "get_order"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"order_id": "ord_1"},
        source="cli",
    )
    assert result.path == "/orders/ord_1"
    assert events == []

    response = await execute_action(
        action_for(app, "get_order"),
        Request(method="POST", path="/__quater__/actions/call"),
        {"order_id": "ord_1"},
        source="cli",
    )

    assert response.body == b'{"id":"ord_1","session":"primary"}'
    await run_response_finalizers(response)
    assert events == ["open:cli", "close:cli"]


@pytest.mark.asyncio
async def test_mcp_tool_resolves_injected_resources_at_execution_time() -> None:
    events: list[str] = []

    async def provider(request: Request) -> AsyncIterator[FakeSession]:
        events.append(f"open:{request.context.source}")
        try:
            yield FakeSession("primary")
        finally:
            events.append(f"close:{request.context.source}")

    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp"])])

    @app.get(
        "/orders/{order_id}",
        tool=True,
        inject={"session": Resource(provider)},
        description="Fetch one order.",
    )
    async def get_order(order_id: str, session: FakeSession) -> dict[str, str]:
        return {"id": order_id, "session": session.label}

    async with TestClient(app) as client:
        response = await client.mcp.tools_call(
            "get_order",
            {"order_id": "ord_1"},
            token="mcp",
        )

    body = response.json()
    assert body["result"]["content"][0]["text"] == (
        '{"id":"ord_1","session":"primary"}'
    )
    assert events == ["open:mcp", "close:mcp"]


@pytest.mark.asyncio
async def test_action_arguments_cannot_supply_injected_values() -> None:
    async def provider() -> FakeSession:
        return FakeSession("primary")

    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    @app.get(
        "/orders/{order_id}",
        cli=True,
        inject={"session": Resource(provider)},
        description="Fetch one order.",
    )
    async def get_order(order_id: str, session: FakeSession) -> dict[str, str]:
        return {"id": order_id, "session": session.label}

    with pytest.raises(BadRequestError, match="Unknown action argument: session"):
        await execute_action(
            action_for(app, "get_order"),
            Request(method="POST", path="/__quater__/actions/call"),
            {"order_id": "ord_1", "session": "fake"},
            source="cli",
        )


_annotation_events: list[str] = []


async def _annotation_session_provider(
    request: Request,
) -> AsyncIterator[FakeSession]:
    _annotation_events.append(f"open:{request.path}")
    try:
        yield FakeSession("primary")
    finally:
        _annotation_events.append(f"close:{request.path}")


_annotation_session = Resource(_annotation_session_provider)
# A reusable alias that carries both the value type and its provider.
SessionDep = Annotated[FakeSession, _annotation_session]


@pytest.mark.asyncio
async def test_resource_in_annotation_resolves_and_cleans_up() -> None:
    _annotation_events.clear()
    app = Quater()

    @app.get("/orders")
    async def list_orders(session: SessionDep) -> dict[str, str]:
        _annotation_events.append(f"handler:{session.label}")
        return {"session": session.label}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.body == b'{"session":"primary"}'
    assert _annotation_events == ["open:/orders", "handler:primary", "close:/orders"]


def test_annotation_resource_is_excluded_from_schemas() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        description="Fetch one order.",
    )
    async def get_order(order_id: str, session: SessionDep) -> dict[str, str]:
        return {"id": order_id, "session": session.label}

    tool = build_tool_registry(app.routes).get("get_order")
    assert tool is not None
    assert tool.input_schema["properties"] == {"order_id": {"type": "string"}}

    action = action_for(app, "get_order")
    assert action.input_schema["properties"] == {"order_id": {"type": "string"}}


@pytest.mark.asyncio
async def test_inject_resource_allows_unresolved_value_type_annotation() -> None:
    events: list[str] = []

    class LocalSession:
        def __init__(self, label: str) -> None:
            self.label = label

    async def provider() -> LocalSession:
        events.append("open")
        return LocalSession("primary")

    app = Quater()

    @app.get("/orders", inject={"session": Resource(provider)})
    async def list_orders(session: LocalSession) -> dict[str, str]:
        return {"session": session.label}

    async with TestClient(app) as client:
        response = await client.get("/orders")

    assert response.body == b'{"session":"primary"}'
    assert events == ["open"]


def test_inject_resource_rejects_malformed_value_type_annotation() -> None:
    async def provider() -> FakeSession:
        return FakeSession("primary")

    app = Quater()

    @app.get("/orders", inject={"session": Resource(provider)})
    async def list_orders(session: FakeSession) -> dict[str, str]:
        return {"session": session.label}

    list_orders.__annotations__["session"] = "Annotated[FakeSession"

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "session" in message
    assert "could not be resolved" in message
    assert "Annotated[FakeSession" in message


def test_unresolved_annotation_resource_alias_is_rejected() -> None:
    app = Quater()
    session_resource = Resource(_annotation_session_provider)
    LocalSessionDep = Annotated[FakeSession, session_resource]

    @app.get("/orders")
    async def list_orders(session: LocalSessionDep) -> dict[str, str]:
        return {"session": session.label}

    with pytest.raises(RouteBindingError) as exc_info:
        app.compile_routes()
    message = str(exc_info.value)
    assert "session" in message
    assert "could not be resolved" in message


def test_resource_declared_in_inject_and_annotation_is_rejected() -> None:
    app = Quater()

    @app.get("/orders", inject={"session": _annotation_session})
    async def list_orders(session: SessionDep) -> dict[str, str]:
        return {"session": session.label}

    with pytest.raises(RouteBindingError, match="both in inject="):
        app.compile_routes()


def test_resource_in_default_slot_is_rejected() -> None:
    app = Quater()

    @app.get("/orders")
    async def list_orders(
        session: FakeSession = _annotation_session,  # type: ignore[assignment]
    ) -> dict[str, str]:
        return {"session": session.label}

    with pytest.raises(RouteBindingError, match="not as a default value"):
        app.compile_routes()
