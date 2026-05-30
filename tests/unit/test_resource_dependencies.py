"""Resources that depend on other resources (issue #53).

A resource provider can ask for other resources the same way handlers do, with
``Annotated[T, resource]``. The framework resolves those dependencies first,
once, from the shared per-request scope, and passes them in. Dependencies are
validated at startup (compile time): cycles and unresolvable parameters fail
loudly before the first request.

Resources whose providers depend on other resources are constructed inside each
test on purpose: that keeps the module importable under the pre-feature code so
each test fails on its own (TDD red) instead of erroring at import.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, contextmanager
from typing import Annotated

import pytest

from quater import (
    AuthContext,
    AuthRequest,
    Quater,
    Request,
    Resource,
    TestClient,
)
from quater.actions.registry import build_action_registry
from quater.exceptions import ConfigurationError
from quater.tools.registry import build_tool_registry


class FakeSession:
    def __init__(self, label: str) -> None:
        self.label = label


async def allow_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject=ctx.context.source)


# --- Module-scope dependency resources (valid today: request/no-arg only) ----
# Their Annotated aliases live at module scope so they type-check and so
# get_type_hints can resolve them when a dependent provider asks for them.

_events: list[str] = []


async def _session_provider(request: Request) -> AsyncIterator[FakeSession]:
    _events.append("open:session")
    try:
        yield FakeSession("primary")
    finally:
        _events.append("close:session")


_session = Resource(_session_provider, name="session")
SessionDep = Annotated[FakeSession, _session]


async def _current_user_provider(
    request: Request,
    session: SessionDep,
) -> AsyncIterator[dict[str, str]]:
    _events.append(f"open:user({session.label})")
    try:
        yield {"id": "u_1", "session": session.label}
    finally:
        _events.append("close:user")


@pytest.mark.asyncio
async def test_resource_can_depend_on_another_resource() -> None:
    _events.clear()
    current_user = Resource(_current_user_provider, name="current_user")
    app = Quater()

    @app.get("/me", inject={"user": current_user})
    async def me(user: dict[str, str]) -> dict[str, str]:
        return user

    async with TestClient(app) as client:
        response = await client.get("/me")

    assert response.body == b'{"id":"u_1","session":"primary"}'
    # Session is built before the user that needs it; user is torn down first.
    assert _events == [
        "open:session",
        "open:user(primary)",
        "close:user",
        "close:session",
    ]


# --- Shared dependency: built once, reused by several dependents -------------

_shared_calls = 0


async def _shared_session_provider() -> FakeSession:
    global _shared_calls
    _shared_calls += 1
    return FakeSession("shared")


_shared_session = Resource(_shared_session_provider, name="session")
SharedSessionDep = Annotated[FakeSession, _shared_session]


async def _reader_provider(session: SharedSessionDep) -> str:
    return f"reader:{session.label}"


async def _writer_provider(session: SharedSessionDep) -> str:
    return f"writer:{session.label}"


@pytest.mark.asyncio
async def test_shared_dependency_is_built_once_per_request() -> None:
    global _shared_calls
    _shared_calls = 0
    reader = Resource(_reader_provider, name="reader")
    writer = Resource(_writer_provider, name="writer")

    app = Quater()

    @app.get(
        "/work",
        inject={"reader": reader, "writer": writer, "session": _shared_session},
    )
    async def work(reader: str, writer: str, session: FakeSession) -> dict[str, object]:
        return {"reader": reader, "writer": writer, "same": session.label}

    async with TestClient(app) as client:
        response = await client.get("/work")

    assert response.body == (
        b'{"reader":"reader:shared","writer":"writer:shared","same":"shared"}'
    )
    # One session for the whole request, reused by both deps and the handler.
    assert _shared_calls == 1


# --- A dependency value is the same object a handler injects directly --------

_identity_box: dict[str, object] = {}


async def _identity_session_provider() -> FakeSession:
    return FakeSession("primary")


_identity_session = Resource(_identity_session_provider, name="session")
IdentitySessionDep = Annotated[FakeSession, _identity_session]


async def _identity_user_provider(session: IdentitySessionDep) -> dict[str, str]:
    _identity_box["dep_session"] = session
    return {"id": "u_1"}


@pytest.mark.asyncio
async def test_dependency_value_is_shared_with_a_direct_handler_injection() -> None:
    _identity_box.clear()
    user = Resource(_identity_user_provider, name="current_user")

    app = Quater()

    @app.get("/me", inject={"user": user, "session": _identity_session})
    async def me(user: dict[str, str], session: FakeSession) -> dict[str, str]:
        _identity_box["handler_session"] = session
        return {"id": user["id"]}

    async with TestClient(app) as client:
        await client.get("/me")

    assert _identity_box["dep_session"] is _identity_box["handler_session"]


# --- Compile-time validation -------------------------------------------------


def test_dependency_cycle_is_rejected_at_compile_time() -> None:
    async def looping_provider(me: object) -> str:
        return "x"

    resource = Resource(looping_provider, name="loops")
    # Point the provider's own parameter at itself to form a one-node cycle.
    looping_provider.__annotations__["me"] = Annotated[str, resource]

    app = Quater()

    @app.get("/x", inject={"value": resource})
    async def handler(value: str) -> dict[str, str]:
        return {"value": value}

    with pytest.raises(ConfigurationError, match="cycle"):
        app.compile_routes()


def test_two_node_dependency_cycle_is_rejected_at_compile_time() -> None:
    async def a_provider(dep: object) -> str:
        return "a"

    async def b_provider(dep: object) -> str:
        return "b"

    a = Resource(a_provider, name="a")
    b = Resource(b_provider, name="b")
    # a needs b, b needs a.
    a_provider.__annotations__["dep"] = Annotated[str, b]
    b_provider.__annotations__["dep"] = Annotated[str, a]

    with pytest.raises(ConfigurationError, match="cycle"):
        _compile_with_resource(a)


@pytest.mark.asyncio
async def test_direct_resolution_of_a_cycle_raises_instead_of_recursing() -> None:
    # Resolving a cyclic resource without going through route compilation must
    # fail loudly rather than recurse until the interpreter stack overflows.
    async def looping_provider(me: object) -> str:
        return "x"

    resource = Resource(looping_provider, name="loops")
    looping_provider.__annotations__["me"] = Annotated[str, resource]

    async with AsyncExitStack() as stack:
        with pytest.raises(ConfigurationError, match="cycle"):
            await resource.resolve(Request(method="GET", path="/x"), stack)


def test_unresolvable_provider_parameter_is_rejected_at_compile_time() -> None:
    async def bad_provider(request: Request, mystery: int) -> str:
        return "nope"

    bad = Resource(bad_provider, name="bad")

    app = Quater()

    @app.get("/x", inject={"value": bad})
    async def handler(value: str) -> dict[str, str]:
        return {"value": value}

    with pytest.raises(ConfigurationError, match="mystery"):
        app.compile_routes()


def _compile_with_resource(resource: Resource) -> None:
    app = Quater()

    @app.get("/x", inject={"value": resource})
    async def handler(value: str) -> dict[str, str]:
        return {"value": value}

    app.compile_routes()


async def _request_and_resource_provider(request: SessionDep) -> str:
    return "x"


async def _two_request_provider(request: Request, other: Request) -> str:
    return "x"


async def _two_resource_provider(
    value: Annotated[FakeSession, _session, _shared_session],
) -> str:
    return "x"


def test_provider_parameter_cannot_be_both_request_and_resource() -> None:
    resource = Resource(_request_and_resource_provider, name="conflict")
    with pytest.raises(ConfigurationError, match="cannot be both"):
        _compile_with_resource(resource)


def test_provider_cannot_accept_the_request_twice() -> None:
    resource = Resource(_two_request_provider, name="double")
    with pytest.raises(ConfigurationError, match="only once"):
        _compile_with_resource(resource)


def test_provider_annotation_with_two_resources_is_rejected() -> None:
    resource = Resource(_two_resource_provider, name="ambiguous")
    with pytest.raises(ConfigurationError, match="[Oo]nly one resource"):
        _compile_with_resource(resource)


# --- Transitive dependencies stay out of caller-facing schemas ---------------


async def _schema_user_provider(session: SessionDep) -> dict[str, str]:
    return {"id": "u_1", "session": session.label}


@pytest.mark.asyncio
async def test_transitive_dependencies_stay_out_of_caller_schemas() -> None:
    user = Resource(_schema_user_provider, name="current_user")
    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        inject={"user": user},
        description="Fetch one order.",
    )
    async def get_order(order_id: str, user: dict[str, str]) -> dict[str, object]:
        return {"id": order_id, "user": user["id"]}

    tool = build_tool_registry(app.routes).get("get_order")
    assert tool is not None
    assert tool.input_schema["properties"] == {"order_id": {"type": "string"}}

    action = build_action_registry(app.routes).get("get_order")
    assert action is not None
    assert action.input_schema["properties"] == {"order_id": {"type": "string"}}


# --- Provider return forms and teardown edge cases ---------------------------


def test_provider_signature_that_cannot_be_inspected_is_rejected() -> None:
    # Some builtins expose no introspectable signature.
    with pytest.raises(ConfigurationError, match="could not be inspected"):
        Resource(min)


NotedSessionDep = Annotated[FakeSession, "the database session", _session]


async def _noted_provider(session: NotedSessionDep) -> str:
    return session.label


@pytest.mark.asyncio
async def test_provider_dependency_annotation_ignores_non_resource_metadata() -> None:
    _events.clear()
    resource = Resource(_noted_provider, name="noted")
    app = Quater()

    @app.get("/noted", inject={"value": resource})
    async def handler(value: str) -> dict[str, str]:
        return {"value": value}

    async with TestClient(app) as client:
        response = await client.get("/noted")

    assert response.body == b'{"value":"primary"}'


@pytest.mark.asyncio
async def test_sync_generator_resource_is_cleaned_up() -> None:
    events: list[str] = []

    def provider() -> Iterator[FakeSession]:
        events.append("open")
        yield FakeSession("sync")
        events.append("close")

    resource = Resource(provider, name="sync")
    app = Quater()

    @app.get("/sync", inject={"session": resource})
    async def handler(session: FakeSession) -> dict[str, str]:
        return {"label": session.label}

    async with TestClient(app) as client:
        response = await client.get("/sync")

    assert response.body == b'{"label":"sync"}'
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_sync_context_manager_resource_is_cleaned_up() -> None:
    events: list[str] = []

    @contextmanager
    def cm_provider() -> Iterator[FakeSession]:
        events.append("open")
        try:
            yield FakeSession("cm")
        finally:
            events.append("close")

    resource = Resource(cm_provider, name="cm")
    app = Quater()

    @app.get("/cm", inject={"session": resource})
    async def handler(session: FakeSession) -> dict[str, str]:
        return {"label": session.label}

    async with TestClient(app) as client:
        response = await client.get("/cm")

    assert response.body == b'{"label":"cm"}'
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_failing_cleanup_still_tears_down_earlier_async_resources() -> None:
    events: list[str] = []

    async def first_provider() -> AsyncIterator[str]:
        events.append("open:first")
        try:
            yield "first"
        except BaseException:
            events.append("first:interrupted")
            raise
        finally:
            events.append("close:first")

    async def second_provider() -> AsyncIterator[str]:
        events.append("open:second")
        yield "second"
        raise RuntimeError("cleanup boom")

    first = Resource(first_provider, name="first")
    second = Resource(second_provider, name="second")
    app = Quater()

    @app.get("/two", inject={"first": first, "second": second})
    async def handler(first: str, second: str) -> dict[str, str]:
        return {"first": first, "second": second}

    async with TestClient(app) as client:
        response = await client.get("/two")

    assert response.body == b'{"first":"first","second":"second"}'
    # second is torn down first; its failing cleanup is thrown into first, which
    # still completes its own teardown.
    assert "first:interrupted" in events
    assert events[-1] == "close:first"


@pytest.mark.asyncio
async def test_failing_cleanup_still_tears_down_earlier_sync_resources() -> None:
    events: list[str] = []

    def first_provider() -> Iterator[str]:
        events.append("open:first")
        try:
            yield "first"
        except BaseException:
            events.append("first:interrupted")
            raise
        finally:
            events.append("close:first")

    def second_provider() -> Iterator[str]:
        events.append("open:second")
        yield "second"
        raise RuntimeError("cleanup boom")

    first = Resource(first_provider, name="first")
    second = Resource(second_provider, name="second")
    app = Quater()

    @app.get("/two", inject={"first": first, "second": second})
    async def handler(first: str, second: str) -> dict[str, str]:
        return {"first": first, "second": second}

    async with TestClient(app) as client:
        response = await client.get("/two")

    assert response.body == b'{"first":"first","second":"second"}'
    assert "first:interrupted" in events
    assert events[-1] == "close:first"
