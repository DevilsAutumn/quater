from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from typing import cast

import pytest

from quater import (
    AuthContext,
    AuthRequest,
    JSONResponse,
    Quater,
    Request,
    Response,
    RouteGroup,
)
from quater.exceptions import ConfigurationError, RouteConflictError
from quater.middleware import ExceptionHandlerEntry
from quater.protocol.actions import ACTIONS_MANIFEST_PATH, ACTIONS_RPC_PATH
from quater.typing import ApprovalRequest


async def allow_auth(ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject=ctx.context.source)


async def approve(ctx: ApprovalRequest) -> bool:
    return True


async def call_mcp_tool(
    app: Quater,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    response = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"content-type": "application/json"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
            ).encode("utf-8"),
        )
    )
    assert response.status_code == 200
    return cast(dict[str, object], json.loads(response.body))


async def call_cli_action(
    app: Quater,
    name: str,
    arguments: dict[str, object],
) -> tuple[int, dict[str, object]]:
    response = await app.handle(
        Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers={"content-type": "application/json"},
            body=json.dumps({"action": name, "arguments": arguments}).encode("utf-8"),
        )
    )
    return response.status_code, cast(dict[str, object], json.loads(response.body))


def tool_text_json(body: dict[str, object]) -> dict[str, object]:
    result = body["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    return cast(dict[str, object], json.loads(text))


@pytest.mark.asyncio
async def test_route_group_flattens_nested_prefixes_and_metadata() -> None:
    app = Quater()
    api = RouteGroup(prefix="/api", tags=["api"])
    orders = RouteGroup(prefix="/orders", tags=["orders"])
    api.include(orders)

    @orders.get("/{order_id:int}", metadata={"tags": ["read"]})
    async def get_order(order_id: int) -> dict[str, int]:
        return {"order_id": order_id}

    app.include(api)

    response = await app.handle(Request(method="GET", path="/api/orders/42"))
    schema = await app.handle(Request(method="GET", path="/openapi.json"))

    assert response.status_code == 200
    assert response.body == b'{"order_id":42}'

    openapi = json.loads(schema.body)
    operation = openapi["paths"]["/api/orders/{order_id}"]["get"]
    assert operation["tags"] == ["api", "orders", "read"]


@pytest.mark.asyncio
async def test_route_group_root_route_joins_to_prefix_without_trailing_slash() -> None:
    app = Quater()
    group = RouteGroup(prefix="/api/")

    @group.get("/")
    async def api_root() -> dict[str, bool]:
        return {"ok": True}

    app.include(group)

    response = await app.handle(Request(method="GET", path="/api"))
    trailing = await app.handle(Request(method="GET", path="/api/"))

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'
    assert trailing.status_code == 200
    assert trailing.body == b'{"ok":true}'


@pytest.mark.asyncio
async def test_route_group_auth_runs_before_route_auth() -> None:
    calls: list[str] = []

    async def group_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(f"group:{ctx.path}")
        return AuthContext(subject="group")

    async def route_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(f"route:{ctx.path}")
        return AuthContext(subject="route")

    app = Quater()
    group = RouteGroup(prefix="/api", auth=group_auth)

    @group.get("/me", auth=route_auth)
    async def me(request: Request) -> dict[str, str]:
        assert request.auth is not None
        return {"subject": request.auth.subject}

    app.include(group)

    response = await app.handle(Request(method="GET", path="/api/me"))

    assert response.status_code == 200
    assert response.body == b'{"subject":"route"}'
    assert calls == ["group:/api/me", "route:/api/me"]


@pytest.mark.asyncio
async def test_route_group_auth_denial_stops_route_auth_and_handler() -> None:
    route_auth_calls = 0
    handler_calls = 0

    async def deny_group(ctx: AuthRequest) -> AuthContext | None:
        return None

    async def route_auth(ctx: AuthRequest) -> AuthContext | None:
        nonlocal route_auth_calls
        route_auth_calls += 1
        return AuthContext(subject="route")

    app = Quater()
    group = RouteGroup(prefix="/api", auth=deny_group)

    @group.get("/private", auth=route_auth)
    async def private() -> dict[str, bool]:
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    app.include(group)

    response = await app.handle(Request(method="GET", path="/api/private"))

    assert response.status_code == 401
    assert route_auth_calls == 0
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_nested_route_group_auth_order_applies_to_mcp_and_cli() -> None:
    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)
    calls: list[tuple[str, str, str]] = []

    async def parent_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(("parent", ctx.context.source, ctx.path))
        return AuthContext(subject=f"parent-{ctx.context.source}")

    async def child_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(("child", ctx.context.source, ctx.path))
        return AuthContext(subject=f"child-{ctx.context.source}")

    async def route_auth(ctx: AuthRequest) -> AuthContext | None:
        calls.append(("route", ctx.context.source, ctx.path))
        return AuthContext(subject=f"route-{ctx.context.source}")

    api = RouteGroup(prefix="/api", auth=parent_auth)
    orders = RouteGroup(prefix="/orders", auth=child_auth)
    api.include(orders)

    @orders.get(
        "/{order_id:int}",
        tool=True,
        cli=True,
        auth=route_auth,
        description="Fetch one nested order.",
    )
    async def get_order(order_id: int, request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {
            "order_id": order_id,
            "source": request.context.source,
            "subject": request.auth.subject,
        }

    app.include(api)

    mcp_body = await call_mcp_tool(app, "get_order", {"order_id": 7})
    cli_status, cli_body = await call_cli_action(app, "get_order", {"order_id": 8})

    assert tool_text_json(mcp_body) == {
        "order_id": 7,
        "source": "mcp",
        "subject": "route-mcp",
    }
    assert cli_status == 200
    assert cli_body["body"] == {
        "order_id": 8,
        "source": "cli",
        "subject": "route-cli",
    }
    assert calls == [
        ("parent", "mcp", "/api/orders/7"),
        ("child", "mcp", "/api/orders/7"),
        ("route", "mcp", "/api/orders/7"),
        ("parent", "cli", "/api/orders/8"),
        ("child", "cli", "/api/orders/8"),
        ("route", "cli", "/api/orders/8"),
    ]


@pytest.mark.asyncio
async def test_route_group_middleware_order_matches_http_routes() -> None:
    app = Quater()
    events: list[str] = []

    async def group_before(request: Request) -> Response | None:
        events.append("group_before")
        return None

    async def route_before(request: Request) -> Response | None:
        events.append("route_before")
        return None

    async def group_around(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        events.append("group_around_before")
        response = await call_next(request)
        events.append("group_around_after")
        return response

    async def route_around(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        events.append("route_around_before")
        response = await call_next(request)
        events.append("route_around_after")
        return response

    async def route_after(request: Request, response: Response) -> Response:
        events.append("route_after")
        return response

    async def group_after(request: Request, response: Response) -> Response:
        events.append("group_after")
        return response

    group = RouteGroup(
        prefix="/api",
        before=[group_before],
        after=[group_after],
        around=[group_around],
    )

    @group.get(
        "/work",
        before=[route_before],
        after=[route_after],
        around=[route_around],
    )
    async def work() -> dict[str, bool]:
        events.append("handler")
        return {"ok": True}

    app.include(group)

    response = await app.handle(Request(method="GET", path="/api/work"))

    assert response.status_code == 200
    assert events == [
        "group_before",
        "route_before",
        "group_around_before",
        "route_around_before",
        "handler",
        "route_around_after",
        "group_around_after",
        "route_after",
        "group_after",
    ]


@pytest.mark.asyncio
async def test_route_exception_handler_wins_over_group_exception_handler() -> None:
    app = Quater()

    async def group_handler(request: Request, exc: Exception) -> Response | None:
        return JSONResponse({"handled": "group"}, status_code=409)

    async def route_handler(request: Request, exc: Exception) -> Response | None:
        return JSONResponse({"handled": "route"}, status_code=418)

    group = RouteGroup(
        prefix="/api",
        exception_handlers=[ExceptionHandlerEntry(ValueError, group_handler)],
    )

    @group.get(
        "/boom",
        exception_handlers=[ExceptionHandlerEntry(ValueError, route_handler)],
    )
    async def boom() -> dict[str, bool]:
        raise ValueError("broken")

    app.include(group)

    response = await app.handle(Request(method="GET", path="/api/boom"))

    assert response.status_code == 418
    assert response.body == b'{"handled":"route"}'


@pytest.mark.asyncio
async def test_route_group_auth_and_middleware_apply_to_mcp_and_cli_actions() -> None:
    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)
    seen_auth: list[tuple[str, str, str]] = []
    seen_before: list[tuple[str, str]] = []

    async def group_auth(ctx: AuthRequest) -> AuthContext | None:
        seen_auth.append((ctx.context.source, ctx.context.action_name or "", ctx.path))
        return AuthContext(subject=f"group-{ctx.context.source}")

    async def group_before(request: Request) -> Response | None:
        seen_before.append((request.context.source, request.path))
        return None

    group = RouteGroup(prefix="/api", auth=group_auth, before=[group_before])

    @group.get(
        "/items/{item_id:int}",
        tool=True,
        cli=True,
        description="Fetch one grouped item.",
    )
    async def get_item(item_id: int, request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {
            "item_id": item_id,
            "source": request.context.source,
            "subject": request.auth.subject,
        }

    app.include(group)

    mcp = await app.handle(
        Request(
            method="POST",
            path="/mcp",
            headers={"content-type": "application/json"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "get_item", "arguments": {"item_id": 3}},
                }
            ).encode("utf-8"),
        )
    )
    cli = await app.handle(
        Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers={"content-type": "application/json"},
            body=json.dumps({"action": "get_item", "arguments": {"item_id": 4}}).encode(
                "utf-8"
            ),
        )
    )

    mcp_body = json.loads(mcp.body)
    cli_body = json.loads(cli.body)

    assert tool_text_json(mcp_body)["subject"] == "group-mcp"
    assert cli_body["body"] == {
        "item_id": 4,
        "source": "cli",
        "subject": "group-cli",
    }
    assert seen_auth == [
        ("mcp", "get_item", "/api/items/3"),
        ("cli", "get_item", "/api/items/4"),
    ]
    assert seen_before == [
        ("mcp", "/api/items/3"),
        ("cli", "/api/items/4"),
    ]


@pytest.mark.asyncio
async def test_group_exception_handler_applies_to_mcp_and_cli_actions() -> None:
    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)

    async def handle_value_error(
        request: Request,
        exc: Exception,
    ) -> Response | None:
        return JSONResponse(
            {"handled": "group", "source": request.context.source},
            status_code=418,
        )

    group = RouteGroup(
        prefix="/api",
        exception_handlers=[ExceptionHandlerEntry(ValueError, handle_value_error)],
    )

    @group.get(
        "/boom",
        tool=True,
        cli=True,
        description="Raise a handled grouped error.",
    )
    async def grouped_boom() -> dict[str, bool]:
        raise ValueError("broken")

    app.include(group)

    mcp_body = await call_mcp_tool(app, "grouped_boom", {})
    cli_status, cli_body = await call_cli_action(app, "grouped_boom", {})

    result = mcp_body["result"]
    assert isinstance(result, dict)
    assert result["isError"] is True
    assert tool_text_json(mcp_body) == {"handled": "group", "source": "mcp"}
    assert cli_status == 418
    assert cli_body["body"] == {"handled": "group", "source": "cli"}


@pytest.mark.asyncio
async def test_action_approval_runs_before_route_group_middleware() -> None:
    app = Quater(cli_auth=allow_auth, action_approval=approve)
    events: list[str] = []

    async def group_before(request: Request) -> Response | None:
        events.append("group_before")
        return None

    group = RouteGroup(prefix="/api", before=[group_before])

    @group.post(
        "/orders",
        cli=True,
        needs_approval=True,
        description="Create one order.",
    )
    async def create_order() -> dict[str, bool]:
        events.append("handler")
        return {"ok": True}

    app.include(group)

    response = await app.handle(
        Request(
            method="POST",
            path=ACTIONS_RPC_PATH,
            headers={"content-type": "application/json"},
            body=b'{"action":"create_order","arguments":{}}',
        )
    )

    assert response.status_code == 409
    assert events == []


def test_route_group_externally_callable_routes_validate_app_auth_on_include() -> None:
    group = RouteGroup(prefix="/api")

    @group.get("/tools", tool=True, description="Read grouped tool.")
    async def read_tool() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match="MCP tools require mcp_auth"):
        Quater().include(group)


def test_route_group_include_is_all_or_nothing_when_validation_fails() -> None:
    group = RouteGroup(prefix="/api")

    @group.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @group.get("/tools", tool=True, description="Read grouped tool.")
    async def read_tool() -> dict[str, bool]:
        return {"ok": True}

    app = Quater()

    with pytest.raises(ConfigurationError, match="MCP tools require mcp_auth"):
        app.include(group)

    assert app.routes == ()

    authenticated_app = Quater(mcp_auth=allow_auth)
    authenticated_app.include(group)
    assert len(authenticated_app.routes) == 2


def test_route_group_cannot_be_included_twice_or_modified_after_include() -> None:
    group = RouteGroup(prefix="/api")

    @group.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app = Quater()
    app.include(group)

    async def late_route() -> dict[str, bool]:
        return {"late": True}

    with pytest.raises(ConfigurationError, match="already been included"):
        app.include(group)
    with pytest.raises(ConfigurationError, match="Cannot modify"):
        group.add_route("GET", "/late", late_route)


def test_nested_route_groups_cannot_be_reused_or_mutated_after_mount() -> None:
    api = RouteGroup(prefix="/api")
    orders = RouteGroup(prefix="/orders")
    api.include(orders)

    with pytest.raises(ConfigurationError, match="top-level"):
        Quater().include(orders)

    app = Quater()
    app.include(api)

    async def late_route() -> dict[str, bool]:
        return {"late": True}

    with pytest.raises(ConfigurationError, match="Cannot modify"):
        orders.add_route("GET", "/late", late_route)


def test_route_groups_can_only_include_a_child_once() -> None:
    first = RouteGroup(prefix="/first")
    second = RouteGroup(prefix="/second")
    child = RouteGroup(prefix="/child")

    first.include(child)

    with pytest.raises(ConfigurationError, match="only be included once"):
        second.include(child)


@pytest.mark.parametrize(
    "prefix",
    (
        "api",
        "/api?debug=true",
        "/api#fragment",
    ),
)
def test_route_group_rejects_invalid_prefixes(prefix: str) -> None:
    with pytest.raises(ConfigurationError, match="RouteGroup prefix"):
        RouteGroup(prefix=prefix)


@pytest.mark.parametrize(
    "tags",
    (
        "api",
        ["api", ""],
    ),
)
def test_route_group_rejects_invalid_tags(tags: object) -> None:
    with pytest.raises(ConfigurationError, match="RouteGroup tags"):
        RouteGroup(tags=cast(Iterable[str], tags))


@pytest.mark.parametrize(
    "path",
    (
        "missing-leading-slash",
        "/users?debug=true",
        "/users#fragment",
    ),
)
def test_route_group_rejects_invalid_route_paths(path: str) -> None:
    group = RouteGroup(prefix="/api")

    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match="RouteGroup route paths"):
        group.add_route("GET", path, handler)


def test_route_conflicts_after_group_prefix_flattening_are_rejected() -> None:
    app = Quater()

    @app.get("/api/users")
    async def direct_users() -> dict[str, bool]:
        return {"direct": True}

    group = RouteGroup(prefix="/api")

    @group.get("/users")
    async def grouped_users() -> dict[str, bool]:
        return {"grouped": True}

    app.include(group)

    with pytest.raises(RouteConflictError):
        app.compile_routes()


@pytest.mark.parametrize(
    "path",
    (
        "/mcp",
        "/mcp/",
        "/mcp/tools",
        "/mcp//tools",
        ACTIONS_MANIFEST_PATH,
        "/.well-known//quater-actions.json",
        "/__quater__",
        ACTIONS_RPC_PATH,
        "/__quater__/other",
    ),
)
def test_quater_protocol_paths_are_reserved_for_user_routes(path: str) -> None:
    app = Quater()

    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match="reserved by Quater"):
        app.add_route("GET", path, handler)


@pytest.mark.parametrize(
    "path",
    (
        "/mcp-tools",
        "/__quaterly",
        "/.well-known/other",
    ),
)
def test_similar_non_protocol_paths_remain_available(path: str) -> None:
    app = Quater()

    async def handler() -> dict[str, bool]:
        return {"ok": True}

    app.add_route("GET", path, handler)

    assert len(app.routes) == 1


@pytest.mark.parametrize(
    ("prefix", "path"),
    (
        ("/mcp", "/tools"),
        ("/.well-known", "/quater-actions.json"),
        ("/__quater__", "/actions/call"),
    ),
)
def test_route_group_cannot_define_quater_protocol_paths(
    prefix: str,
    path: str,
) -> None:
    app = Quater()
    group = RouteGroup(prefix=prefix)

    @group.get(path)
    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match="reserved by Quater"):
        app.include(group)
