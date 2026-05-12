"""Tool registry built from route metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from quater.actions.executor import execute_action
from quater.core import RouteDefinition
from quater.exceptions import ConfigurationError
from quater.params import HandlerPlan, build_handler_plan
from quater.request import Request
from quater.response import Response
from quater.routing import RoutePattern, parse_route_pattern
from quater.tools.descriptions import resolve_tool_description
from quater.tools.schema import tool_input_schema
from quater.typing import ActionApproval, Authenticate


@dataclass(slots=True, frozen=True)
class ToolDefinition:
    name: str
    description: str
    route: RouteDefinition
    pattern: RoutePattern
    handler_plan: HandlerPlan
    input_schema: dict[str, object]

    async def call(
        self,
        request: Request,
        arguments: Mapping[str, object],
        *,
        authenticated_by: Authenticate | None = None,
        approval_hook: ActionApproval | None = None,
        approval_token: str | None = None,
        debug: bool = False,
    ) -> Response:
        return await execute_action(
            self,
            request,
            arguments,
            source="mcp",
            authenticated_by=authenticated_by,
            approval_hook=approval_hook,
            approval_token=approval_token,
            debug=debug,
        )

    def as_mcp_tool(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass(slots=True, frozen=True)
class ToolRegistry:
    tools: Mapping[str, ToolDefinition]

    def list_tools(self) -> list[dict[str, object]]:
        return [tool.as_mcp_tool() for tool in self.tools.values()]

    def get(self, name: str) -> ToolDefinition | None:
        return self.tools.get(name)


def build_tool_registry(routes: tuple[RouteDefinition, ...]) -> ToolRegistry:
    tools: dict[str, ToolDefinition] = {}
    for route in routes:
        if not route.tool:
            continue

        name = route.name
        if name in tools:
            raise ConfigurationError(f"Duplicate tool name: {name}")

        pattern = parse_route_pattern(route.path)
        handler_plan = build_handler_plan(
            route.handler,
            path_param_names=pattern.param_names,
        )
        tools[name] = ToolDefinition(
            name=name,
            description=resolve_tool_description(
                route.name,
                route.description,
                route.handler,
            ),
            route=route,
            pattern=pattern,
            handler_plan=handler_plan,
            input_schema=tool_input_schema(handler_plan.parameters),
        )

    return ToolRegistry(tools=tools)
