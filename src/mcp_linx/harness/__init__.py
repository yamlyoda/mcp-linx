"""Harness — модуль обвязки для MCP-Linx.

Реализует идеологию "Everything is a plugin":
- Агентный цикл как плагин
- Автообнаружение плагинов
- Песочница как плагин
- Компакция контекста как плагин
"""

from mcp_linx.harness.agent_loop import AgentLoop, DefaultAgentLoop
from mcp_linx.harness.plugin_manager import PluginManager, discover_plugins
from mcp_linx.harness.sandbox import Sandbox, LocalSandbox, DockerSandbox
from mcp_linx.harness.context import ContextCompactor, SlidingWindowCompactor

__all__ = [
    "AgentLoop",
    "DefaultAgentLoop",
    "PluginManager",
    "discover_plugins",
    "Sandbox",
    "LocalSandbox",
    "DockerSandbox",
    "ContextCompactor",
    "SlidingWindowCompactor",
]
