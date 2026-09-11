"""Harness — модуль обвязки для MCP-Linx.

Реализует идеологию "Everything is a plugin":
- Агентный цикл как плагин
- Автообнаружение плагинов
- Песочница как плагин
- Компакция контекста как плагин
"""

from mcp_linx.harness.agent_loop import AgentLoop, DefaultAgentLoop, StreamingAgentLoop
from mcp_linx.harness.context import ContextCompactor, SlidingWindowCompactor
from mcp_linx.harness.plugin_manager import PluginManager, discover_plugins
from mcp_linx.harness.sandbox import DockerSandbox, LocalSandbox, Sandbox

__all__ = [
    "AgentLoop",
    "DefaultAgentLoop",
    "StreamingAgentLoop",
    "PluginManager",
    "discover_plugins",
    "Sandbox",
    "LocalSandbox",
    "DockerSandbox",
    "ContextCompactor",
    "SlidingWindowCompactor",
]
