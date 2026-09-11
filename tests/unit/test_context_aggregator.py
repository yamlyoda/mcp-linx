"""Тесты ContextAggregator - Часть 1"""

from __future__ import annotations

import pytest

from mcp_linx.context_aggregator import ContextAggregator
from mcp_linx.types import ComponentState, Status


class TestContextAggregator:
    """Тесты для ContextAggregator"""

    @pytest.fixture
    def aggregator(self) -> ContextAggregator:
        return ContextAggregator()

    def test_add_component(self, aggregator: ContextAggregator):
        """Добавление компонента"""
        state = ComponentState(
            plugin_id="linux",
            status=Status.HEALTHY,
            last_checked="2024-01-01T00:00:00Z",
        )
        aggregator.add_component(state)

        components = aggregator.get_components()
        assert len(components) == 1
        assert components[0].plugin_id == "linux"

    def test_add_multiple_components(self, aggregator: ContextAggregator):
        """Добавление нескольких компонентов"""
        for plugin_id in ["linux", "nginx", "docker"]:
            state = ComponentState(
                plugin_id=plugin_id,
                status=Status.HEALTHY,
                last_checked="2024-01-01T00:00:00Z",
            )
            aggregator.add_component(state)

        components = aggregator.get_components()
        assert len(components) == 3
        assert {c.plugin_id for c in components} == {"linux", "nginx", "docker"}

    def test_get_component_by_id(self, aggregator: ContextAggregator):
        """Получение компонента по ID"""
        state = ComponentState(
            plugin_id="linux",
            status=Status.HEALTHY,
            last_checked="2024-01-01T00:00:00Z",
        )
        aggregator.add_component(state)

        component = aggregator.get_component("linux")
        assert component is not None
        assert component.plugin_id == "linux"
        assert component.status == Status.HEALTHY

    def test_get_nonexistent_component(self, aggregator: ContextAggregator):
        """Получение несуществующего компонента возвращает None"""
        assert aggregator.get_component("nonexistent") is None

    def test_clear(self, aggregator: ContextAggregator):
        """Очистка контекста"""
        for plugin_id in ["linux", "nginx"]:
            state = ComponentState(
                plugin_id=plugin_id,
                status=Status.HEALTHY,
                last_checked="2024-01-01T00:00:00Z",
            )
            aggregator.add_component(state)

        assert len(aggregator.get_components()) == 2

        aggregator.clear()

        assert len(aggregator.get_components()) == 0

    def test_build_context(self, aggregator: ContextAggregator):
        """Сбор контекста"""
        for plugin_id in ["linux", "nginx"]:
            state = ComponentState(
                plugin_id=plugin_id,
                status=Status.HEALTHY,
                last_checked="2024-01-01T00:00:00Z",
            )
            aggregator.add_component(state)

        context = aggregator.build_context(host_id="test-host")

        assert context.host_id == "test-host"
        assert len(context.components) == 2
        assert context.timestamp is not None

    def test_get_overall_status_healthy(self, aggregator: ContextAggregator):
        """Общий статус healthy когда все компоненты healthy"""
        for plugin_id in ["linux", "nginx"]:
            state = ComponentState(
                plugin_id=plugin_id,
                status=Status.HEALTHY,
                last_checked="2024-01-01T00:00:00Z",
            )
            aggregator.add_component(state)

        overall = aggregator.get_overall_status()
        assert overall == Status.HEALTHY

    def test_get_overall_status_critical(self, aggregator: ContextAggregator):
        """Общий статус critical если есть критический компонент"""
        linux_state = ComponentState(
            plugin_id="linux",
            status=Status.HEALTHY,
            last_checked="2024-01-01T00:00:00Z",
        )
        nginx_state = ComponentState(
            plugin_id="nginx",
            status=Status.CRITICAL,
            last_checked="2024-01-01T00:00:00Z",
        )

        aggregator.add_component(linux_state)
        aggregator.add_component(nginx_state)

        overall = aggregator.get_overall_status()
        assert overall == Status.CRITICAL

    def test_get_overall_status_degraded(self, aggregator: ContextAggregator):
        """Общий статус degraded если есть degraded компонент"""
        linux_state = ComponentState(
            plugin_id="linux",
            status=Status.HEALTHY,
            last_checked="2024-01-01T00:00:00Z",
        )
        nginx_state = ComponentState(
            plugin_id="nginx",
            status=Status.DEGRADED,
            last_checked="2024-01-01T00:00:00Z",
        )

        aggregator.add_component(linux_state)
        aggregator.add_component(nginx_state)

        overall = aggregator.get_overall_status()
        assert overall == Status.DEGRADED


class TestContextAggregatorNewCorrelations:
    """Тесты для новых корреляций (Phase 3)"""

    @pytest.fixture
    def aggregator(self) -> ContextAggregator:
        return ContextAggregator()

    def test_oom_restart_nginx_correlation(self, aggregator: ContextAggregator):
        """OOM killer → container restart → Nginx 5xx: тройная цепочка"""
        aggregator.add_component(
            ComponentState(
                plugin_id="linux",
                status=Status.CRITICAL,
                last_checked="2024-01-01T00:00:00Z",
                issues=["Out of memory: killed process 1234 (nginx)"],
            )
        )
        aggregator.add_component(
            ComponentState(
                plugin_id="docker",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["Container webapp restart count 5"],
            )
        )
        aggregator.add_component(
            ComponentState(
                plugin_id="nginx",
                status=Status.CRITICAL,
                last_checked="2024-01-01T00:00:00Z",
                issues=["upstream timed out"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        oom_corr = [
            c
            for c in ctx.correlations
            if c.source == "linux" and "docker" in c.related and "nginx" in c.related
        ]
        assert len(oom_corr) >= 1

    def test_postgres_idle_in_transaction(self, aggregator: ContextAggregator):
        """PostgreSQL idle-in-transaction — root cause suspected"""
        aggregator.add_component(
            ComponentState(
                plugin_id="postgres",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["idle in transaction", "blocked queries"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        pg_corr = [
            c for c in ctx.correlations if c.source == "postgres" and "idle" in c.evidence.lower()
        ]
        assert len(pg_corr) >= 1

    def test_postgres_replication_lag(self, aggregator: ContextAggregator):
        """PostgreSQL replication lag + Nginx degraded"""
        aggregator.add_component(
            ComponentState(
                plugin_id="postgres",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["replication lag 30s"],
            )
        )
        aggregator.add_component(
            ComponentState(
                plugin_id="nginx",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["upstream timed out"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        repl_corr = [
            c
            for c in ctx.correlations
            if c.source == "postgres"
            and "nginx" in c.related
            and "replication" in c.evidence.lower()
        ]
        assert len(repl_corr) >= 1

    def test_linux_no_space_docker_prune(self, aggregator: ContextAggregator):
        """Linux no space left → docker_prune recommendation"""
        aggregator.add_component(
            ComponentState(
                plugin_id="linux",
                status=Status.CRITICAL,
                last_checked="2024-01-01T00:00:00Z",
                issues=["no space left on device /var/lib/docker"],
            )
        )
        aggregator.add_component(
            ComponentState(
                plugin_id="docker",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["image build failed"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        disk_corr = [
            c
            for c in ctx.correlations
            if c.source == "linux" and "docker" in c.related and "space" in c.evidence.lower()
        ]
        assert len(disk_corr) >= 1


class TestContextAggregatorIncident504:
    """Тесты корреляций INCIDENT_504: SYN-дроп, per-uid, DB_HOST mismatch"""

    @pytest.fixture
    def aggregator(self) -> ContextAggregator:
        return ContextAggregator()

    def test_timeout_equals_proxy_timeout(self, aggregator: ContextAggregator):
        """Таймаут == proxy_connect_timeout → L3/L4 дроп, а не медленный код"""
        aggregator.add_component(
            ComponentState(
                plugin_id="nginx",
                status=Status.CRITICAL,
                last_checked="2024-01-01T00:00:00Z",
                metrics={"proxy_connect_timeout_s": 3.0, "upstream_connect_ms": 3003.6},
                issues=["upstream timed out while connecting to upstream"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        corr = [c for c in ctx.correlations if c.source == "nginx" and "linux" in c.related]
        assert len(corr) >= 1
        assert "proxy_connect_timeout" in corr[0].evidence

    def test_timeout_match_without_metrics(self, aggregator: ContextAggregator):
        """Таймаут без замеров — всё равно L3/L4-подозрение"""
        aggregator.add_component(
            ComponentState(
                plugin_id="nginx",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["upstream timed out"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        corr = [c for c in ctx.correlations if c.source == "nginx"]
        assert len(corr) >= 1

    def test_no_correlation_when_times_differ(self, aggregator: ContextAggregator):
        """Быстрый таймаут (не равен proxy_connect_timeout) — не L3/L4 корреляция"""
        aggregator.add_component(
            ComponentState(
                plugin_id="nginx",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                metrics={"proxy_connect_timeout_s": 30.0, "upstream_connect_ms": 500.0},
                issues=["upstream timed out"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        corr = [c for c in ctx.correlations if c.source == "nginx"]
        assert len(corr) == 0

    def test_per_uid_filter_correlation(self, aggregator: ContextAggregator):
        """Проба проходит от одного uid, падает от сервисного → per-uid фильтр"""
        aggregator.add_component(
            ComponentState(
                plugin_id="netdiag",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["Connect as www-data failed — возможен per-uid фильтр (nft skuid)"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        corr = [c for c in ctx.correlations if c.source == "netdiag"]
        assert len(corr) >= 1
        assert "systemd" in corr[0].related

    def test_db_host_mismatch_correlation(self, aggregator: ContextAggregator):
        """DB_HOST vs listen_addresses mismatch"""
        aggregator.add_component(
            ComponentState(
                plugin_id="postgres",
                status=Status.DEGRADED,
                last_checked="2024-01-01T00:00:00Z",
                issues=["DB_HOST=127.0.0.1 not in listen_addresses (10.0.0.5)"],
            )
        )

        ctx = aggregator.build_context()
        assert ctx.correlations is not None
        corr = [c for c in ctx.correlations if c.source == "postgres" and "DB_HOST" in c.evidence]
        assert len(corr) >= 1
