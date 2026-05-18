"""Internal registry for routes exposed outside plain HTTP."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from quater.actions.descriptions import resolve_action_description
from quater.core import RouteDefinition
from quater.exceptions import ConfigurationError
from quater.params import HandlerPlan, build_handler_plan
from quater.routing import RoutePattern, parse_route_pattern
from quater.tools.schema import tool_input_schema


@dataclass(slots=True, frozen=True)
class ActionDefinition:
    name: str
    description: str
    route: RouteDefinition
    pattern: RoutePattern
    handler_plan: HandlerPlan
    input_schema: dict[str, object]
    cli: bool
    tool: bool
    needs_approval: bool


@dataclass(slots=True, frozen=True)
class ActionRegistry:
    actions: Mapping[str, ActionDefinition]

    def get(self, name: str) -> ActionDefinition | None:
        return self.actions.get(name)

    def cli_actions(self) -> tuple[ActionDefinition, ...]:
        return tuple(action for action in self.actions.values() if action.cli)

    def tool_actions(self) -> tuple[ActionDefinition, ...]:
        return tuple(action for action in self.actions.values() if action.tool)


def build_action_registry(routes: tuple[RouteDefinition, ...]) -> ActionRegistry:
    actions: dict[str, ActionDefinition] = {}
    for route in routes:
        if not route.cli and not route.tool:
            continue

        if route.name in actions:
            raise ConfigurationError(f"Duplicate action name: {route.name}")

        pattern = parse_route_pattern(route.path)
        handler_plan = build_handler_plan(
            route.handler,
            path_param_names=pattern.param_names,
            inject=route.inject,
        )
        if any(parameter.source == "file" for parameter in handler_plan.parameters):
            raise ConfigurationError(
                "Routes with File parameters cannot be exposed as MCP tools "
                "or CLI actions"
            )
        actions[route.name] = ActionDefinition(
            name=route.name,
            description=route.description
            or resolve_action_description(
                "Action",
                route.name,
                route.description,
                route.handler,
            ),
            route=route,
            pattern=pattern,
            handler_plan=handler_plan,
            input_schema=tool_input_schema(handler_plan.parameters),
            cli=route.cli,
            tool=route.tool,
            needs_approval=route.needs_approval,
        )

    return ActionRegistry(actions=MappingProxyType(actions))
