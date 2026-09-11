"""Unit tests for new plugins part 2: k8s, prometheus, loki + correlations"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_plugin(plugin_class, methods: dict):
    plugin = MagicMock(spec=plugin_class)
    for name, ret in methods.items():
        setattr(plugin, name, AsyncMock(return_value=ret))
    return plugin


class TestKubernetesTools:
    @pytest.mark.asyncio
    async def test_k8s_pods_bad(self):
        from mcp_linx.plugins.kubernetes import KubernetesPlugin
        from mcp_linx.plugins.kubernetes.tools import k8s_pods
        from mcp_linx.types import Status

        payload = {
            "items": [
                {
                    "metadata": {"name": "web-0"},
                    "spec": {"nodeName": "n1"},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {
                                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                                "restartCount": 10,
                                "ready": False,
                            }
                        ],
                    },
                }
            ]
        }
        plugin = _make_plugin(
            KubernetesPlugin,
            {
                "_run": {"stdout": json.dumps(payload), "stderr": "", "returncode": 0},
            },
        )
        plugin._kubectl_base = MagicMock(return_value="kubectl")
        plugin._namespace = "default"
        result = await k8s_pods(plugin, {})
        assert result.status == Status.DEGRADED
        assert result.data["problem"] == 1

    @pytest.mark.asyncio
    async def test_k8s_logs_bad_pod(self):
        from mcp_linx.plugins.kubernetes import KubernetesPlugin
        from mcp_linx.plugins.kubernetes.tools import k8s_logs
        from mcp_linx.types import Status

        plugin = _make_plugin(KubernetesPlugin, {})
        plugin._namespace = "default"
        result = await k8s_logs(plugin, {"pod": "../evil"})
        assert result.status == Status.ERROR


class TestPrometheusTools:
    @pytest.mark.asyncio
    async def test_prom_query_empty(self):
        from mcp_linx.plugins.prometheus import PrometheusPlugin
        from mcp_linx.plugins.prometheus.tools import prom_query
        from mcp_linx.types import Status

        plugin = MagicMock(spec=PrometheusPlugin)
        result = await prom_query(plugin, {"query": ""})
        assert result.status == Status.ERROR


class TestLokiTools:
    @pytest.mark.asyncio
    async def test_log_search_empty(self):
        from mcp_linx.plugins.loki import LokiPlugin
        from mcp_linx.plugins.loki.tools import log_search
        from mcp_linx.types import Status

        plugin = MagicMock(spec=LokiPlugin)
        result = await log_search(plugin, {"query": ""})
        assert result.status == Status.ERROR


class TestNewCorrelations:
    def test_redis_pg_cascade(self):
        from mcp_linx.context_aggregator import ContextAggregator
        from mcp_linx.types import ComponentState, Status

        agg = ContextAggregator()
        agg.add_component(
            ComponentState("redis", Status.DEGRADED, "t", issues=["evicted_keys=100"])
        )
        agg.add_component(ComponentState("postgres", Status.CRITICAL, "t"))
        ctx = agg.build_context()
        assert any(
            c.source == "redis" and "postgres" in c.related for c in (ctx.correlations or [])
        )

    def test_k8s_oom_correlation(self):
        from mcp_linx.context_aggregator import ContextAggregator
        from mcp_linx.types import ComponentState, Status

        agg = ContextAggregator()
        agg.add_component(
            ComponentState("kubernetes", Status.CRITICAL, "t", issues=["CrashLoopBackOff in web-0"])
        )
        agg.add_component(
            ComponentState("linux", Status.DEGRADED, "t", issues=["memory pressure high"])
        )
        ctx = agg.build_context()
        assert any(
            c.source == "linux" and "kubernetes" in c.related for c in (ctx.correlations or [])
        )
