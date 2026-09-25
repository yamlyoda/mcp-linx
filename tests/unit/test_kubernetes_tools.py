"""Unit tests для `plugins/kubernetes/tools.py` (волна 14).

Без кластера: `plugin._run` возвращает заготовленный вывод `kubectl`,
`_kubectl_base`/`_namespace` подменяются. Покрываем парсинг JSON-вывода,
degraded-ветки (проблемные поды/ивенты/деплойменты) и ошибки kubectl.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from conftest import make_plugin as _make_plugin

from mcp_linx.types import Status


def _k8s(stdout: str, returncode: int = 0, stderr: str = ""):
    """KubernetesPlugin-двойник с ответом kubectl."""
    from mcp_linx.plugins.kubernetes import KubernetesPlugin

    plugin = _make_plugin(
        KubernetesPlugin,
        {"_run": {"stdout": stdout, "stderr": stderr, "returncode": returncode}},
    )
    plugin._kubectl_base = MagicMock(return_value="kubectl")
    plugin._namespace = "default"
    return plugin


def _pod(name: str, phase: str = "Running", restarts: int = 0, ready: bool = True) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"nodeName": "n1"},
        "status": {
            "phase": phase,
            "containerStatuses": [
                {"state": {}, "restartCount": restarts, "ready": ready},
            ],
        },
    }


class TestK8sPods:
    @pytest.mark.asyncio
    async def test_all_healthy(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_pods

        plugin = _k8s(json.dumps({"items": [_pod("web-0"), _pod("api-0")]}))
        result = await k8s_pods(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["total"] == 2
        assert result.data["problem"] == 0

    @pytest.mark.asyncio
    async def test_many_restarts_is_problem(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_pods

        plugin = _k8s(json.dumps({"items": [_pod("web-0", restarts=7)]}))
        result = await k8s_pods(plugin, {})

        assert result.status == Status.DEGRADED
        assert result.data["problem"] == 1
        assert result.data["pods"][0]["restarts"] == 7

    @pytest.mark.asyncio
    async def test_pending_phase_is_problem(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_pods

        plugin = _k8s(json.dumps({"items": [_pod("web-0", phase="Pending", ready=False)]}))
        result = await k8s_pods(plugin, {})

        assert result.status == Status.DEGRADED
        assert result.data["pods"][0]["phase"] == "Pending"

    @pytest.mark.asyncio
    async def test_kubectl_failure(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_pods

        plugin = _k8s("", returncode=1, stderr="connection refused")
        result = await k8s_pods(plugin, {})

        assert result.status == Status.ERROR
        assert "connection refused" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_pods

        plugin = _k8s("not json")
        result = await k8s_pods(plugin, {})

        assert result.status == Status.ERROR


class TestK8sEvents:
    @pytest.mark.asyncio
    async def test_no_warnings_is_healthy(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_events

        items = [
            {
                "type": "Normal",
                "reason": "Started",
                "message": "Started container",
                "involvedObject": {"kind": "Pod", "name": "web-0"},
            }
        ]
        plugin = _k8s(json.dumps({"items": items}))
        result = await k8s_events(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["warnings"] == 0
        assert result.data["events"][0]["object"] == "Pod/web-0"

    @pytest.mark.asyncio
    async def test_warnings_are_degraded(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_events

        items = [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "involvedObject": {"kind": "Pod", "name": "web-0"},
            }
        ]
        plugin = _k8s(json.dumps({"items": items}))
        result = await k8s_events(plugin, {})

        assert result.status == Status.DEGRADED
        assert result.data["warnings"] == 1

    @pytest.mark.asyncio
    async def test_kubectl_failure(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_events

        plugin = _k8s("", returncode=1, stderr="forbidden")
        result = await k8s_events(plugin, {})

        assert result.status == Status.ERROR


class TestK8sLogs:
    @pytest.mark.asyncio
    async def test_returns_logs(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_logs

        plugin = _k8s("app started\nready\n")
        result = await k8s_logs(plugin, {"pod": "web-0", "lines": 50})

        assert result.status == Status.HEALTHY
        assert result.data["pod"] == "web-0"
        assert "ready" in result.data["logs"]

    @pytest.mark.asyncio
    async def test_command_includes_container_and_previous(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_logs

        plugin = _k8s("crash log\n")
        await k8s_logs(plugin, {"pod": "web-0", "container": "app", "previous": True, "lines": 20})

        cmd = plugin._run.await_args.args[0]
        assert "-c app" in cmd
        assert cmd.endswith(" -p")
        assert "--tail=20" in cmd

    @pytest.mark.asyncio
    async def test_kubectl_failure(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_logs

        plugin = _k8s("", returncode=1, stderr="pod not found")
        result = await k8s_logs(plugin, {"pod": "web-0"})

        assert result.status == Status.ERROR
        assert "pod not found" in (result.error_message or "")


class TestK8sDescribe:
    @pytest.mark.asyncio
    async def test_ready_pod(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_describe

        pod = {
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [{"name": "app", "ready": True}],
            }
        }
        plugin = _k8s(json.dumps(pod))
        result = await k8s_describe(plugin, {"pod": "web-0"})

        assert result.status == Status.HEALTHY
        assert result.data["phase"] == "Running"
        assert result.data["conditions"][0]["type"] == "Ready"

    @pytest.mark.asyncio
    async def test_not_ready_is_degraded(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_describe

        pod = {
            "status": {
                "phase": "Running",
                "conditions": [
                    {"type": "Ready", "status": "False", "reason": "ContainersNotReady"}
                ],
            }
        }
        plugin = _k8s(json.dumps(pod))
        result = await k8s_describe(plugin, {"pod": "web-0"})

        assert result.status == Status.DEGRADED
        assert any("not Ready" in s for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_kubectl_failure(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_describe

        plugin = _k8s("", returncode=1, stderr="not found")
        result = await k8s_describe(plugin, {"pod": "web-0"})

        assert result.status == Status.ERROR


class TestK8sTopAndDeployments:
    @pytest.mark.asyncio
    async def test_top_parses_rows(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_top

        plugin = _k8s("web-0   12m   64Mi\napi-0   35m   128Mi\n")
        result = await k8s_top(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["pods"] == [
            {"pod": "web-0", "cpu": "12m", "memory": "64Mi"},
            {"pod": "api-0", "cpu": "35m", "memory": "128Mi"},
        ]

    @pytest.mark.asyncio
    async def test_top_failure(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_top

        plugin = _k8s("", returncode=1, stderr="metrics-server unavailable")
        result = await k8s_top(plugin, {})

        assert result.status == Status.ERROR
        assert "metrics-server" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_deployments_all_available(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_deployments

        items = [{"metadata": {"name": "web"}, "status": {"replicas": 2, "availableReplicas": 2}}]
        plugin = _k8s(json.dumps({"items": items}))
        result = await k8s_deployments(plugin, {})

        assert result.status == Status.HEALTHY
        assert result.data["degraded"] == 0

    @pytest.mark.asyncio
    async def test_deployments_missing_replicas_degraded(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_deployments

        items = [{"metadata": {"name": "web"}, "status": {"replicas": 3, "availableReplicas": 1}}]
        plugin = _k8s(json.dumps({"items": items}))
        result = await k8s_deployments(plugin, {})

        assert result.status == Status.DEGRADED
        assert result.data["deployments"][0]["available"] == 1

    @pytest.mark.asyncio
    async def test_deployments_kubectl_failure(self):
        from mcp_linx.plugins.kubernetes.tools import k8s_deployments

        plugin = _k8s("", returncode=1, stderr="forbidden")
        result = await k8s_deployments(plugin, {})

        assert result.status == Status.ERROR
