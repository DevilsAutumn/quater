from __future__ import annotations

import pytest

import quater.tools as tools
from quater.tools.audit import ToolAuditEvent
from quater.tools.registry import ToolDefinition, ToolRegistry, build_tool_registry


def test_tools_package_lazily_exposes_public_symbols() -> None:
    module_dict = vars(tools)
    for name in tools.__all__:
        module_dict.pop(name, None)

    assert tools.ToolAuditEvent is ToolAuditEvent
    assert tools.ToolDefinition is ToolDefinition
    assert tools.ToolRegistry is ToolRegistry
    assert tools.build_tool_registry is build_tool_registry


def test_tools_package_rejects_unknown_lazy_attributes() -> None:
    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        tools.__getattr__("missing")
