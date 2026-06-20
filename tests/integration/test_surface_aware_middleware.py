from __future__ import annotations

import asyncio
import json
import sys
import types
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from quater import Quater, Request, Response, TestClient, TextResponse
from quater.cli.main import main as cli_main
from quater.exceptions import ConfigurationError, MiddlewareStateError
from quater.middleware import ExceptionHandlerEntry


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def register_app_module(
    monkeypatch: pytest.MonkeyPatch,
    app: Quater,
) -> str:
    module_name = f"_quater_surface_middleware_app_{id(app)}"
    module = cast(Any, types.ModuleType(module_name))
    module.app = app
    monkeypatch.setitem(sys.modules, module_name, module)
    return f"{module_name}:app"


def mcp_result_text(response: Any) -> str:
    payload = response.json()
    result = payload["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    return str(content[0]["text"])


def test_global_middleware_can_target_api_mcp_and_cli_surfaces(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Quater()
    events: list[str] = []

    @app.before_request(surfaces=["api"])
    async def require_request_id(request: Request) -> Response | None:
        events.append(f"api-before:{request.context.source}:{request.path}")
        if request.headers.get("x-request-id") is None:
            return TextResponse("Missing request id", status_code=400)
        return None

    @app.before_request(surfaces=["mcp"])
    async def tag_mcp_tool_call(request: Request) -> Response | None:
        events.append(f"mcp-before:{request.context.source}:{request.path}")
        return None

    @app.before_request(surfaces=["cli"])
    async def tag_cli_action_call(request: Request) -> Response | None:
        events.append(
            f"cli-before:{request.context.source}:"
            f"{request.context.entrypoint}:{request.path}"
        )
        return None

    @app.after_response(surfaces=["api"])
    async def add_browser_cookie(request: Request, response: Response) -> Response:
        events.append(f"api-after:{request.context.source}:{request.path}")
        response.headers = (
            *response.headers,
            ("set-cookie", "seen=true; Path=/"),
        )
        return response

    @app.around_request(surfaces=["mcp", "cli"])
    async def time_agent_operation(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        events.append(
            "agent-around-before:"
            f"{request.context.source}:{request.context.entrypoint}:{request.path}"
        )
        response = await call_next(request)
        events.append(
            "agent-around-after:"
            f"{request.context.source}:{request.context.entrypoint}:{request.path}"
        )
        return response

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        description="Fetch one order.",
    )
    async def get_order(order_id: str, request: Request) -> dict[str, str]:
        events.append(
            f"handler:{request.context.source}:"
            f"{request.context.entrypoint}:{request.path}"
        )
        return {
            "order_id": order_id,
            "source": request.context.source,
            "entrypoint": request.context.entrypoint,
        }

    http = run(
        TestClient(app).get(
            "/orders/ord_1001",
            headers={"x-request-id": "req-1"},
        )
    )

    assert http.status_code == 200
    assert http.json() == {
        "order_id": "ord_1001",
        "source": "api",
        "entrypoint": "server",
    }
    assert http.headers.get("set-cookie") == "seen=true; Path=/"
    assert events == [
        "api-before:api:/orders/ord_1001",
        "handler:api:server:/orders/ord_1001",
        "api-after:api:/orders/ord_1001",
    ]

    events.clear()
    mcp = run(TestClient(app).mcp.tools_call("get_order", {"order_id": "ord_1001"}))

    assert mcp.status_code == 200
    assert json.loads(mcp_result_text(mcp)) == {
        "order_id": "ord_1001",
        "source": "mcp",
        "entrypoint": "server",
    }
    assert events == [
        "mcp-before:mcp:/orders/ord_1001",
        "agent-around-before:mcp:server:/orders/ord_1001",
        "handler:mcp:server:/orders/ord_1001",
        "agent-around-after:mcp:server:/orders/ord_1001",
    ]

    events.clear()
    remote_cli = run(TestClient(app).cli.call("get_order", {"order_id": "ord_1001"}))

    assert remote_cli.status_code == 200
    assert remote_cli.json()["body"] == {
        "order_id": "ord_1001",
        "source": "cli",
        "entrypoint": "server",
    }
    assert events == [
        "cli-before:cli:server:/orders/ord_1001",
        "agent-around-before:cli:server:/orders/ord_1001",
        "handler:cli:server:/orders/ord_1001",
        "agent-around-after:cli:server:/orders/ord_1001",
    ]

    events.clear()
    module_target = register_app_module(monkeypatch, app)
    capsys.readouterr()

    exit_code = cli_main(
        [
            "--app",
            module_target,
            "--json",
            "call",
            "get_order",
            "--order-id",
            "ord_1001",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["body"] == {
        "order_id": "ord_1001",
        "source": "cli",
        "entrypoint": "local",
    }
    assert events == [
        "cli-before:cli:local:/orders/ord_1001",
        "agent-around-before:cli:local:/orders/ord_1001",
        "handler:cli:local:/orders/ord_1001",
        "agent-around-after:cli:local:/orders/ord_1001",
    ]


def test_surface_scoped_exception_handlers_choose_matching_surface() -> None:
    app = Quater()
    events: list[str] = []

    @app.exception_handler(RuntimeError, surfaces=["api"])
    async def handle_api_error(request: Request, exc: Exception) -> Response | None:
        events.append(f"api-handler:{request.context.source}")
        return TextResponse("api mapped", status_code=409)

    @app.exception_handler(RuntimeError, surfaces=["mcp"])
    async def handle_mcp_error(request: Request, exc: Exception) -> Response | None:
        events.append(f"mcp-handler:{request.context.source}")
        return TextResponse("mcp mapped", status_code=418)

    @app.exception_handler(RuntimeError, surfaces=["cli"])
    async def handle_cli_error(request: Request, exc: Exception) -> Response | None:
        events.append(f"cli-handler:{request.context.source}")
        return TextResponse("cli mapped", status_code=419)

    @app.get("/boom", tool=True, cli=True, description="Raise a handler error.")
    async def boom() -> dict[str, bool]:
        raise RuntimeError("secret detail")

    http = run(TestClient(app).get("/boom"))
    assert http.status_code == 409
    assert http.text == "api mapped"

    mcp = run(TestClient(app).mcp.tools_call("boom", {}))
    assert mcp.status_code == 200
    assert mcp_result_text(mcp) == "mcp mapped"
    assert mcp.json()["result"]["isError"] is True

    remote_cli = run(TestClient(app).cli.call("boom", {}))
    assert remote_cli.status_code == 419
    assert remote_cli.json()["body"] == "cli mapped"

    assert events == [
        "api-handler:api",
        "mcp-handler:mcp",
        "cli-handler:cli",
    ]


def test_default_global_and_route_middleware_stay_all_surface_compatible() -> None:
    app = Quater()
    events: list[str] = []

    @app.before_request
    async def global_before(request: Request) -> Response | None:
        events.append(f"global:{request.context.source}:{request.path}")
        return None

    async def route_before(request: Request) -> Response | None:
        events.append(f"route:{request.context.source}:{request.path}")
        return None

    @app.get(
        "/orders/{order_id}",
        tool=True,
        cli=True,
        description="Fetch one order.",
        before=[route_before],
    )
    async def get_order(order_id: str) -> dict[str, str]:
        return {"order_id": order_id}

    run(TestClient(app).get("/orders/ord_1001"))
    run(TestClient(app).mcp.tools_call("get_order", {"order_id": "ord_1001"}))
    run(TestClient(app).cli.call("get_order", {"order_id": "ord_1001"}))

    assert events == [
        "global:api:/orders/ord_1001",
        "route:api:/orders/ord_1001",
        "global:mcp:/orders/ord_1001",
        "route:mcp:/orders/ord_1001",
        "global:cli:/orders/ord_1001",
        "route:cli:/orders/ord_1001",
    ]


def test_route_exception_handler_wins_over_surface_scoped_global_handler() -> None:
    app = Quater()

    @app.exception_handler(RuntimeError, surfaces=["api"])
    async def global_handler(request: Request, exc: Exception) -> Response | None:
        return TextResponse("global", status_code=500)

    async def route_handler(request: Request, exc: Exception) -> Response | None:
        return TextResponse("route", status_code=409)

    @app.get(
        "/boom",
        exception_handlers=[ExceptionHandlerEntry(RuntimeError, route_handler)],
    )
    async def boom() -> dict[str, bool]:
        raise RuntimeError("bad")

    response = run(TestClient(app).get("/boom"))

    assert response.status_code == 409
    assert response.text == "route"


def test_surface_middleware_rejects_invalid_surface_configuration() -> None:
    app = Quater()

    async def middleware(request: Request) -> Response | None:
        return None

    with pytest.raises(ConfigurationError, match="Unknown middleware surface 'web'"):
        app.before_request(surfaces=["web"])(middleware)

    with pytest.raises(ConfigurationError, match="must be a list of surface names"):
        app.after_response(surfaces="api")(cast(Any, middleware))

    with pytest.raises(ConfigurationError, match="must cover at least one surface"):
        app.around_request(surfaces=[])(cast(Any, middleware))

    with pytest.raises(ConfigurationError, match="surface 'api' more than once"):
        app.before_request(surfaces=["api", "api"])(middleware)

    with pytest.raises(ConfigurationError, match="surface 'cli' more than once"):
        app.exception_handler(RuntimeError, surfaces=["cli", "cli"])(
            cast(Any, middleware)
        )


def test_surface_validation_does_not_mask_late_middleware_registration() -> None:
    app = Quater()
    app.compile_routes()

    async def before(request: Request) -> Response | None:
        return None

    async def after(request: Request, response: Response) -> Response:
        return response

    async def around(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await call_next(request)

    async def handler(request: Request, exc: Exception) -> Response | None:
        return None

    with pytest.raises(MiddlewareStateError, match="after routes are compiled"):
        app.before_request(before, surfaces=["web"])

    with pytest.raises(MiddlewareStateError, match="after routes are compiled"):
        app.before_request(surfaces=["web"])(before)

    with pytest.raises(MiddlewareStateError, match="after routes are compiled"):
        app.after_response(surfaces=["web"])(after)

    with pytest.raises(MiddlewareStateError, match="after routes are compiled"):
        app.around_request(surfaces=["web"])(around)

    with pytest.raises(MiddlewareStateError, match="after routes are compiled"):
        app.exception_handler(RuntimeError, surfaces=["web"])(handler)
