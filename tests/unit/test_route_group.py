from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, cast

import pytest

from quater import (
    AuthConfig,
    AuthContext,
    JSONResponse,
    Quater,
    Request,
    Resource,
    Response,
    RouteGroup,
)
from quater.exceptions import ConfigurationError, RouteConflictError
from quater.middleware import ExceptionHandlerEntry
from quater.protocol.actions import ACTIONS_MANIFEST_PATH, ACTIONS_RPC_PATH
from quater.typing import ApprovalRequest


async def allow_auth(ctx: Request) -> AuthContext | None:
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
async def test_app_and_group_routes_share_definition_construction() -> None:
    async def value_provider() -> str:
        return "shared"

    resource = Resource(value_provider)
    inject = {"value": resource}
    metadata = {"feature": "routing", "tags": ["parity"]}
    events: list[str] = []

    async def route_before(request: Request) -> Response | None:
        events.append("before")
        return None

    async def route_around(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        events.append("around_before")
        response = await call_next(request)
        events.append("around_after")
        return response

    async def route_after(request: Request, response: Response) -> Response:
        events.append("after")
        return response

    async def route_exception(
        request: Request,
        exc: Exception,
    ) -> Response | None:
        return JSONResponse({"handled": True}, status_code=418)

    exception_handlers = [ExceptionHandlerEntry(ValueError, route_exception)]

    async def shared_handler(value: str) -> dict[str, str]:
        """Read the shared route."""

        events.append("handler")
        return {"value": value}

    direct_app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])
    grouped_app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])
    group = RouteGroup(prefix="/api")

    direct_route = direct_app.add_route(
        "get",
        "/shared",
        shared_handler,
        tool=True,
        cli=True,
        public=["mcp", "cli"],
        inject=inject,
        metadata=metadata,
        before=[route_before],
        after=[route_after],
        around=[route_around],
        exception_handlers=exception_handlers,
    )
    grouped_route = group.add_route(
        "get",
        "/shared",
        shared_handler,
        tool=True,
        cli=True,
        public=["mcp", "cli"],
        inject=inject,
        metadata=metadata,
        before=[route_before],
        after=[route_after],
        around=[route_around],
        exception_handlers=exception_handlers,
    )

    assert direct_route.method == grouped_route.method == "GET"
    assert direct_route.path == grouped_route.path == "/shared"
    assert direct_route.handler is grouped_route.handler is shared_handler
    assert direct_route.name == grouped_route.name == "shared_handler"
    assert (
        direct_route.description
        == grouped_route.description
        == "Read the shared route."
    )
    assert direct_route.public == grouped_route.public == ("mcp", "cli")
    assert direct_route.inject == grouped_route.inject == inject
    assert direct_route.inject is not inject
    assert grouped_route.inject is not inject
    assert direct_route.metadata == grouped_route.metadata == metadata
    assert direct_route.metadata is not metadata
    assert grouped_route.metadata is not metadata
    assert direct_route.middleware == grouped_route.middleware

    direct_response = await direct_app.handle(Request(method="GET", path="/shared"))

    assert direct_response.status_code == 200
    assert direct_response.body == b'{"value":"shared"}'
    assert events == [
        "before",
        "around_before",
        "handler",
        "around_after",
        "after",
    ]

    events.clear()
    grouped_app.include(group)
    grouped_response = await grouped_app.handle(
        Request(method="GET", path="/api/shared")
    )

    assert grouped_response.status_code == 200
    assert grouped_response.body == b'{"value":"shared"}'
    assert events == [
        "before",
        "around_before",
        "handler",
        "around_after",
        "after",
    ]


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
async def test_route_group_put_route_joins_to_prefix() -> None:
    app = Quater()
    group = RouteGroup(prefix="/api")

    @group.put("/items/{item_id:int}")
    async def replace(item_id: int, payload: dict[str, object]) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    app.include(group)

    response = await app.handle(
        Request(
            method="PUT",
            path="/api/items/7",
            headers=[("content-type", "application/json")],
            body=b'{"name":"Ada"}',
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"item_id": 7, "payload": {"name": "Ada"}}


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
async def test_route_group_middleware_applies_to_mcp_and_cli_actions() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])
    seen_before: list[tuple[str, str]] = []

    async def group_before(request: Request) -> Response | None:
        seen_before.append((request.context.source, request.path))
        return None

    group = RouteGroup(prefix="/api", before=[group_before])

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

    assert tool_text_json(mcp_body)["subject"] == "mcp"
    assert cli_body["body"] == {
        "item_id": 4,
        "source": "cli",
        "subject": "cli",
    }
    assert seen_before == [
        ("mcp", "/api/items/3"),
        ("cli", "/api/items/4"),
    ]


@pytest.mark.asyncio
async def test_group_exception_handler_applies_to_mcp_and_cli_actions() -> None:
    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["mcp", "cli"])])

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
    app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])], action_approval=approve
    )
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


def test_route_group_tool_routes_without_mcp_auth_compile() -> None:
    group = RouteGroup(prefix="/api")

    @group.get("/tools", tool=True, description="Read grouped tool.")
    async def read_tool() -> dict[str, bool]:
        return {"ok": True}

    app = Quater()
    app.include(group)
    app.compile_routes()  # mcp is simply uncovered and open, not an error

    assert app._compiled_tool_registry().get("read_tool") is not None


def test_route_group_include_is_all_or_nothing_when_validation_fails() -> None:
    group = RouteGroup(prefix="/api")

    @group.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @group.post("/charge", cli=True, needs_approval=True, description="Charge.")
    async def charge() -> dict[str, bool]:
        return {"ok": True}

    app = Quater(auth=[AuthConfig(allow_auth, surfaces=["cli"])])

    with pytest.raises(ConfigurationError, match="action_approval"):
        app.include(group)

    assert app.routes == ()

    approved_app = Quater(
        auth=[AuthConfig(allow_auth, surfaces=["cli"])],
        action_approval=approve,
    )
    approved_app.include(group)
    assert len(approved_app.routes) == 2


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


def test_route_group_rejects_self_include() -> None:
    group = RouteGroup()

    with pytest.raises(
        ConfigurationError,
        match="Route groups cannot include themselves",
    ):
        group.include(group)


def test_route_group_rejects_include_cycle() -> None:
    parent = RouteGroup(prefix="/parent")
    child = RouteGroup(prefix="/child")
    parent.include(child)

    with pytest.raises(
        ConfigurationError,
        match="Route groups cannot include themselves",
    ):
        child.include(parent)


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


def test_route_group_rejects_invalid_inject_parameter_names() -> None:
    async def provider() -> str:
        return "bad"

    with pytest.raises(ConfigurationError, match="Invalid injected parameter name"):
        RouteGroup(inject={"bad-name": Resource(provider)})


def test_route_group_rejects_non_resource_inject_values() -> None:
    with pytest.raises(TypeError, match="inject values must be Resource instances"):
        RouteGroup(inject=cast(Any, {"value": object()}))


def test_app_route_path_validation_runs_before_public_surface_validation() -> None:
    app = Quater()

    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match="reserved by Quater"):
        app.get("/mcp", public=["mcp"])(handler)


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
