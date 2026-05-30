"""Per-request resource scope: one shared place for the session and resources.

Covers issue #52 — a single per-request resolution scope (exit stack + cache)
that is created lazily, shared between the auth request and the handler request,
torn down once in reverse order, and never leaks between requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from quater import Quater, Request, Resource, StreamResponse, TestClient
from quater.params import build_handler_plan


class FakeSession:
    def __init__(self, label: str) -> None:
        self.label = label


@pytest.mark.asyncio
async def test_resources_do_not_leak_between_requests() -> None:
    opened: list[int] = []

    async def session_provider() -> AsyncIterator[FakeSession]:
        label = len(opened)
        opened.append(label)
        try:
            yield FakeSession(f"session-{label}")
        finally:
            pass

    app = Quater()

    @app.get("/orders", inject={"session": Resource(session_provider)})
    async def list_orders(session: FakeSession) -> dict[str, str]:
        return {"session": session.label}

    async with TestClient(app) as client:
        first = await client.get("/orders")
        second = await client.get("/orders")

    assert first.body == b'{"session":"session-0"}'
    assert second.body == b'{"session":"session-1"}'
    assert opened == [0, 1]


@pytest.mark.asyncio
async def test_resources_close_in_reverse_order_of_opening() -> None:
    events: list[str] = []

    async def resource_a() -> AsyncIterator[str]:
        events.append("open:a")
        try:
            yield "a"
        finally:
            events.append("close:a")

    async def resource_b() -> AsyncIterator[str]:
        events.append("open:b")
        try:
            yield "b"
        finally:
            events.append("close:b")

    app = Quater()

    @app.get(
        "/two",
        inject={"a": Resource(resource_a), "b": Resource(resource_b)},
    )
    async def handler(a: str, b: str) -> dict[str, str]:
        return {"a": a, "b": b}

    async with TestClient(app) as client:
        response = await client.get("/two")

    assert response.body == b'{"a":"a","b":"b"}'
    assert events == ["open:a", "open:b", "close:b", "close:a"]


@pytest.mark.asyncio
async def test_no_resource_scope_is_created_when_handler_uses_no_resources() -> None:
    app = Quater()

    @app.get("/plain")
    async def plain() -> dict[str, bool]:
        return {"ok": True}

    request = Request(method="GET", path="/plain")
    response = await app.handle(request)

    assert response.status_code == 200
    # Lazy: a request that resolves no resources never allocates a scope.
    assert request._resource_scope is None


@pytest.mark.asyncio
async def test_resource_scope_stays_open_until_stream_is_consumed() -> None:
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
async def test_scope_is_torn_down_when_resolution_fails_midway() -> None:
    events: list[str] = []

    async def good_resource() -> AsyncIterator[str]:
        events.append("open:good")
        try:
            yield "good"
        finally:
            events.append("close:good")

    async def failing_resource() -> AsyncIterator[str]:
        events.append("open:bad")
        raise RuntimeError("provider exploded")
        yield "never"  # pragma: no cover

    app = Quater()

    @app.get(
        "/half-open",
        inject={"good": Resource(good_resource), "bad": Resource(failing_resource)},
    )
    async def handler(good: str, bad: str) -> dict[str, str]:
        return {"good": good, "bad": bad}

    request = Request(method="GET", path="/half-open")
    response = await app.handle(request)

    assert response.status_code == 500
    # The resource that did open must be torn down even though a later one failed.
    assert events == ["open:good", "open:bad", "close:good"]


@pytest.mark.asyncio
async def test_adopted_scope_is_shared_so_a_resource_resolves_once() -> None:
    calls = 0

    async def session_provider() -> FakeSession:
        nonlocal calls
        calls += 1
        return FakeSession("primary")

    resource = Resource(session_provider)

    async def handler(session: FakeSession) -> dict[str, str]:
        return {"session": session.label}

    plan = build_handler_plan(
        handler,
        path_param_names=frozenset(),
        inject={"session": resource},
    )

    auth_request = Request(method="GET", path="/orders")
    handler_request = Request(method="GET", path="/orders")
    handler_request._adopt_resource_scope(auth_request)

    # The auth request resolves the session first (as #54's auth will),
    # the handler request must reuse the very same instance.
    auth_kwargs = await plan.bind(auth_request, {})
    handler_kwargs = await plan.bind(handler_request, {})

    assert handler_kwargs["session"] is auth_kwargs["session"]
    assert calls == 1

    await auth_request._aclose_resources()


@pytest.mark.asyncio
async def test_adopting_a_scope_allocates_nothing_until_a_resource_resolves() -> None:
    auth_request = Request(method="GET", path="/orders")
    handler_request = Request(method="GET", path="/orders")
    handler_request._adopt_resource_scope(auth_request)

    # Sharing is lazy: a request pair that never touches a resource (e.g. a
    # body-carrying action whose handler injects nothing) allocates no scope.
    assert auth_request._resource_scope is None
    assert handler_request._resource_scope is None
    assert handler_request.has_open_resources is False


@pytest.mark.asyncio
async def test_independent_requests_do_not_share_a_scope() -> None:
    async def provider() -> FakeSession:
        return FakeSession("primary")

    resource = Resource(provider)

    async def handler(session: FakeSession) -> dict[str, str]:
        return {"session": session.label}

    plan = build_handler_plan(
        handler,
        path_param_names=frozenset(),
        inject={"session": resource},
    )

    first = Request(method="GET", path="/orders")
    second = Request(method="GET", path="/orders")

    first_kwargs = await plan.bind(first, {})
    second_kwargs = await plan.bind(second, {})

    assert first_kwargs["session"] is not second_kwargs["session"]

    await first._aclose_resources()
    await second._aclose_resources()
