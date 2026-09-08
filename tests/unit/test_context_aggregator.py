"""Тесты ContextAggregator - Часть 1"""

from __future__ import annotations

import pytest

from mcp_linx.context_aggregator import ContextAggregator
from mcp_linx.types import ComponentState, Status, Correlation


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
