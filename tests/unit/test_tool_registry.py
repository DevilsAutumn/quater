from __future__ import annotations

import logging
from typing import Any, cast

import pytest

from quater import AuthConfig, Quater, Request
from quater.actions import executor as action_executor
from quater.core import RouteDefinition
from quater.exceptions import ConfigurationError
from quater.tools import registry as tool_registry_module
from quater.tools.registry import ToolRegistry, build_tool_registry
from quater.typing import AuthContext


async def allow_mcp_auth(ctx: Request) -> AuthContext | None:
    return AuthContext(subject="mcp")


def test_registry_exposes_only_routes_marked_as_tools() -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    @app.get("/private")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/public", tool=True)
    async def public() -> dict[str, bool]:
        """Return the public status."""
        return {"ok": True}

    registry = build_tool_registry(app.routes)

    assert list(registry.tools) == ["public"]
    assert registry.tools["public"].description == "Return the public status."


def test_explicit_tool_description_overrides_handler_docstring() -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    @app.get("/public", tool=True, description="Return public status for agents.")
    async def public() -> dict[str, bool]:
        """This fallback docstring should not be used."""
        return {"ok": True}

    registry = build_tool_registry(app.routes)

    assert registry.list_tools()[0]["description"] == "Return public status for agents."


def test_tool_routes_must_define_a_description() -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    with pytest.raises(ConfigurationError, match="non-empty description"):

        @app.get("/public", tool=True)
        async def public() -> dict[str, bool]:
            return {"ok": True}


def test_registry_defensively_rejects_missing_tool_description() -> None:
    async def public() -> dict[str, bool]:
        return {"ok": True}

    route = RouteDefinition(
        method="GET",
        path="/public",
        handler=public,
        name="public",
        tool=True,
    )

    with pytest.raises(ConfigurationError, match="non-empty description"):
        build_tool_registry((route,))


def test_tool_descriptions_have_a_reasonable_size_limit() -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    with pytest.raises(ConfigurationError, match="1000 characters"):

        @app.get("/public", tool=True, description="x" * 1001)
        async def public() -> dict[str, bool]:
            return {"ok": True}


def test_duplicate_tool_names_fail_when_registry_is_built() -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    @app.get("/users/{id:int}", tool=True, name="lookup", description="Find a user.")
    async def lookup_user(id: int) -> dict[str, int]:
        return {"id": id}

    @app.get(
        "/orders/{id:int}",
        tool=True,
        name="lookup",
        description="Find an order.",
    )
    async def lookup_order(id: int) -> dict[str, int]:
        return {"id": id}

    with pytest.raises(ConfigurationError, match="Duplicate tool name"):
        build_tool_registry(app.routes)


def test_app_builds_tool_registry_during_route_compile() -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    @app.get("/items/{id:int}", tool=True, description="Fetch one item.")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    app.compile_routes()

    assert app._compiled_tool_registry().get("get_item") is not None


def test_app_compiles_dirty_tool_registry_once(monkeypatch: pytest.MonkeyPatch) -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])
    registry_builds = 0
    original_build_tool_registry = tool_registry_module.build_tool_registry

    def build_once(
        routes: tuple[RouteDefinition, ...],
        **kwargs: Any,
    ) -> ToolRegistry:
        nonlocal registry_builds
        registry_builds += 1
        return original_build_tool_registry(routes, **kwargs)

    monkeypatch.setattr(tool_registry_module, "build_tool_registry", build_once)

    @app.get("/items/{id:int}", tool=True, description="Fetch one item.")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    assert app._compiled_tool_registry().get("get_item") is not None
    assert app._compiled_tool_registry().get("get_item") is not None
    assert app._compiled_tool_registry().get("get_item") is not None
    assert registry_builds == 1


def test_app_rebuilds_missing_tool_registry_with_current_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])], debug=True)
    captured_kwargs: list[dict[str, Any]] = []
    original_build_tool_registry = tool_registry_module.build_tool_registry

    @app.before_request
    async def global_before(request: Request) -> None:
        return None

    @app.get("/items/{id:int}", tool=True, description="Fetch one item.")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    app.compile_routes()

    def build_once(
        routes: tuple[RouteDefinition, ...],
        **kwargs: Any,
    ) -> ToolRegistry:
        captured_kwargs.append(kwargs)
        return original_build_tool_registry(routes, **kwargs)

    monkeypatch.setattr(tool_registry_module, "build_tool_registry", build_once)
    app._tool_registry = None

    registry = app._compiled_tool_registry()

    assert registry.get("get_item") is not None
    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["middleware"] is app._middleware
    assert captured_kwargs[0]["debug"] is True


def test_tool_routes_without_an_mcp_auth_are_allowed_but_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater()

    @app.get("/items/{id:int}", tool=True, description="Fetch one item.")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    with caplog.at_level(logging.WARNING, logger="quater"):
        app.compile_routes()

    assert app._compiled_tool_registry().get("get_item") is not None
    assert any(
        "'mcp' surface" in record.message and "get_item" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_tool_call_default_global_stack_stays_empty_after_app_compile() -> None:
    events: list[str] = []
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    @app.before_request
    async def global_before(request: Request) -> None:
        events.append("global_before")

    @app.get("/items/{id:int}", tool=True, description="Fetch one item.")
    async def get_item(id: int) -> dict[str, int]:
        events.append("handler")
        return {"id": id}

    app.compile_routes()
    tool = app._compiled_tool_registry().get("get_item")
    assert tool is not None

    response = await tool.call(
        Request(method="POST", path="/mcp"),
        {"id": 7},
    )

    assert response.body == b'{"id":7}'
    assert events == ["handler"]


@pytest.mark.asyncio
async def test_tool_call_reuses_default_registry_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_compiles = 0
    original_compile = cast(Any, action_executor).compile_middleware_pipeline
    app = Quater(auth=[AuthConfig(allow_mcp_auth, surfaces=["mcp"])])

    def compile_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal pipeline_compiles
        pipeline_compiles += 1
        return original_compile(*args, **kwargs)

    monkeypatch.setattr(
        action_executor,
        "compile_middleware_pipeline",
        compile_once,
    )

    @app.get("/items/{id:int}", tool=True, description="Fetch one item.")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    tool = build_tool_registry(app.routes).get("get_item")
    assert tool is not None
    compiles_after_registry_build = pipeline_compiles

    for id_ in range(3):
        response = await tool.call(
            Request(method="POST", path="/mcp"),
            {"id": id_},
        )
        assert response.status_code == 200

    assert pipeline_compiles == compiles_after_registry_build
