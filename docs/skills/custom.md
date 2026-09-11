# Custom Skills — свой плагин, конфиг, MCP-клиент

Часть Skills (см. `docs/SKILLS.md`). Идеология — `core.md`.

## Creating Custom Skills

### 1. Create Plugin

```bash
mkdir -p plugins/my_skill
touch plugins/my_skill/__init__.py
touch plugins/my_skill/tools.py
```

### 2. Define Plugin

```python
# plugins/my_skill/__init__.py
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.types import HealthStatus, PluginConfig, Status

class MySkillPlugin(DiagnosticPlugin):
    id = "my_skill"
    name = "My Skill"
    description = "Custom skill"

    def get_tools(self) -> list[PluginTool]:
        from .tools import my_tool
        return [PluginTool("my_tool", "Description", my_tool)]

    async def initialize(self, config: PluginConfig) -> None:
        self._config = config

    async def health_check(self) -> HealthStatus:
        return HealthStatus(Status.HEALTHY, "OK")

    async def destroy(self) -> None:
        pass
```

### 3. Implement Tool

```python
# plugins/my_skill/tools.py
from typing import Any
from mcp_linx.plugins.my_skill import MySkillPlugin
from mcp_linx.types import ToolResult

async def my_tool(plugin: MySkillPlugin, params: dict[str, Any]) -> ToolResult:
    try:
        return ToolResult.ok({"result": "data"})
    except Exception as e:
        return ToolResult.error(str(e))
```

### 4. Enable in Config

```yaml
plugins:
  enabled: [linux, nginx, docker, postgres, my_skill]
```

## Configuration

```yaml
plugins:
  linux:
    ssh:
      host: "server1.example.com"
      key_file: "~/.ssh/id_rsa"
  nginx:
    log_path: "/var/log/nginx"
  docker:
    host: "tcp://docker-host:2375"
  postgres:
    host: "db.example.com"
    password: "${POSTGRES_PASSWORD}"
  netdiag:
    privileged_tools: false  # tcp_connect_as / tcpdump_probe — только чтение с лимитами
```

## MCP Client Setup

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "mcp-linx": {
      "command": "python",
      "args": ["-m", "mcp_linx.main"]
    }
  }
}
```
