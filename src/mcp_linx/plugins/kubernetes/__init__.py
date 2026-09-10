"""Kubernetes плагин для MCP-Linx"""

from __future__ import annotations

from typing import Any

from mcp_linx.adapters.base import BaseAdapter, LocalAdapter
from mcp_linx.adapters.ssh import SSHAdapter
from mcp_linx.plugins.base import DiagnosticPlugin, PluginTool
from mcp_linx.security import SecurityGuard
from mcp_linx.types import HealthStatus, PluginConfig, Status


class KubernetesPlugin(DiagnosticPlugin):
    """Плагин диагностики Kubernetes: pods, events, logs, deployments"""

    id = "kubernetes"
    name = "Kubernetes"
    description = "Диагностика Kubernetes: pods, events, logs, describe, top, deployments"
    version = "1.0.0"

    def __init__(self):
        self._adapter: BaseAdapter | None = None
        self._security: SecurityGuard | None = None
        self._namespace = "default"
        self._kubeconfig: str | None = None
        self._context: str | None = None

    def get_tools(self) -> list[PluginTool]:
        from mcp_linx.plugins.kubernetes.tools import (
            k8s_pods,
            k8s_events,
            k8s_logs,
            k8s_describe,
            k8s_top,
            k8s_deployments,
        )

        return [
            PluginTool("k8s_pods", "Список подов с фазами и рестартами", k8s_pods),
            PluginTool("k8s_events", "События кластера/неймспейса (kubectl get events)", k8s_events),
            PluginTool("k8s_logs", "Логи пода (kubectl logs)", k8s_logs),
            PluginTool("k8s_describe", "Describe пода (conditions, events)", k8s_describe),
            PluginTool("k8s_top", "Ресурсы подов (kubectl top pods)", k8s_top),
            PluginTool("k8s_deployments", "Статус деплойментов", k8s_deployments),
        ]

    async def initialize(self, config: PluginConfig) -> None:
        ssh_config = config.get("ssh", {})
        host_ssh = ssh_config.get("host") if isinstance(ssh_config, dict) else None
        self._namespace = str(config.get("namespace", "default"))
        self._kubeconfig = config.get("kubeconfig") or None
        self._context = config.get("context") or None
        if host_ssh:
            self._adapter = SSHAdapter(ssh_config)
        else:
            self._adapter = LocalAdapter({})
        sec = config.get("security", {}) if isinstance(config.get("security"), dict) else {}
        self._security = SecurityGuard({
            "readonly": bool(sec.get("readonly", True)),
            "max_command_output_size": int(sec.get("max_command_output_size", config.get("max_command_output_size", 20000))),
            "max_log_lines": int(sec.get("max_log_lines", config.get("max_log_lines", 200))),
            "command_timeout_seconds": int(sec.get("command_timeout_seconds", config.get("command_timeout_seconds", 20))),
            "allowed_hosts": sec.get("allowed_hosts", ["localhost", "127.0.0.1"]),
        })
        await self._adapter.connect()

    async def health_check(self) -> HealthStatus:
        try:
            result = await self._run("kubectl version --client=true -o json", timeout=10)
            import json as _json
            if result["returncode"] == 0:
                info = _json.loads(result["stdout"] or "{}")
                ver = info.get("clientVersion", {}).get("gitVersion", "unknown")
                return HealthStatus(Status.HEALTHY, f"kubectl available ({ver})")
            cluster = await self._run("kubectl cluster-info", timeout=15)
            if cluster["returncode"] == 0:
                return HealthStatus(Status.HEALTHY, "Cluster reachable")
            return HealthStatus(Status.DEGRADED, "kubectl client only, cluster not reachable")
        except Exception as e:
            return HealthStatus(Status.ERROR, f"Health check failed: {e}")

    async def destroy(self) -> None:
        if self._adapter:
            await self._adapter.disconnect()

    def _kubectl_base(self) -> str:
        import shlex

        parts = ["kubectl"]
        if self._kubeconfig:
            parts += ["--kubeconfig", shlex.quote(self._kubeconfig)]
        if self._context:
            parts += ["--context", shlex.quote(self._context)]
        return " ".join(parts)

    async def _run(self, command: str, timeout: int = 20):
        if not self._adapter or not self._security:
            raise RuntimeError("Plugin not initialized")
        self._security.validate_command(command)
        try:
            result = await self._adapter.execute_command(command, timeout)
            result["stdout"] = self._security.limit_log_lines(result["stdout"])
            return result
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": 1, "command": command}
