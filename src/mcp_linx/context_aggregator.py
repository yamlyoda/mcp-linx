"""Context aggregator для MCP-Linx"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp_linx.types import (
    ComponentState,
    Correlation,
    DiagnosticContext,
    Status,
)


class ContextAggregator:
    """Агрегация контекста из нескольких плагинов для корреляции проблем"""
    
    def __init__(self):
        self._components: dict[str, ComponentState] = {}
    
    def add_component(self, state: ComponentState) -> None:
        """Добавить состояние компонента"""
        self._components[state.plugin_id] = state
    
    def get_components(self) -> list[ComponentState]:
        """Все зарегистрированные компоненты"""
        return list(self._components.values())
    
    def get_component(self, plugin_id: str) -> ComponentState | None:
        """Получить компонент по ID"""
        return self._components.get(plugin_id)
    
    def clear(self) -> None:
        """Очистить контекст"""
        self._components.clear()
    
    def build_context(self, host_id: str = "localhost") -> DiagnosticContext:
        """Собрать полный контекст диагностики"""
        components = list(self._components.values())
        correlations = self._find_correlations(components)
        
        return DiagnosticContext(
            timestamp=datetime.now(timezone.utc).isoformat(),
            host_id=host_id,
            components=components,
            correlations=correlations,
        )
    
    def _find_correlations(self, components: list[ComponentState]) -> list[Correlation]:
        """Поиск корреляций между компонентами"""
        correlations: list[Correlation] = []
        
        # Корреляция: Docker + Nginx
        docker_state = self._get_component_by_plugin(components, "docker")
        nginx_state = self._get_component_by_plugin(components, "nginx")
        
        if docker_state and nginx_state:
            if docker_state.status in [Status.DEGRADED, Status.CRITICAL] and nginx_state.status == Status.CRITICAL:
                correlations.append(
                    Correlation(
                        type="cascade",
                        source="docker",
                        related=["nginx"],
                        evidence="Docker containers may be down, causing Nginx upstream failures",
                    )
                )
            
            if docker_state.status == Status.HEALTHY and nginx_state.status == Status.CRITICAL:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="nginx",
                        related=["docker"],
                        evidence="Nginx is down but Docker containers are running — possible Nginx configuration or process issue",
                    )
                )
        
        # Корреляция: Linux + Docker
        linux_state = self._get_component_by_plugin(components, "linux")
        
        if linux_state and docker_state:
            if linux_state.status in [Status.CRITICAL, Status.ERROR] and docker_state.status in [Status.DEGRADED, Status.CRITICAL]:
                correlations.append(
                    Correlation(
                        type="cascade",
                        source="linux",
                        related=["docker"],
                        evidence="System resources issues (CPU/memory/disk) may cause Docker container failures",
                    )
                )
        
        # Корреляция: PostgreSQL + Docker + Application
        postgres_state = self._get_component_by_plugin(components, "postgres")
        
        if docker_state and postgres_state:
            if postgres_state.status in [Status.DEGRADED, Status.CRITICAL] and docker_state.status == Status.HEALTHY:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="postgres",
                        related=["docker"],
                        evidence="PostgreSQL is degraded but containers are running — application may be experiencing database connectivity issues",
                    )
                )
        
        # Корреляция: Redis evictions + PostgreSQL slow → cache-miss cascade
        redis_state = self._get_component_by_plugin(components, "redis")

        if redis_state and postgres_state:
            redis_issues = " ".join(redis_state.issues or []).lower()
            if ("evict" in redis_issues or "maxmemory" in redis_issues) and postgres_state.status in [
                Status.DEGRADED, Status.CRITICAL,
            ]:
                correlations.append(
                    Correlation(
                        type="cascade",
                        source="redis",
                        related=["postgres"],
                        evidence="Redis evictions detected while PostgreSQL is slow — cache-miss cascade likely",
                    )
                )

        # Корреляция: Kubernetes CrashLoop + Linux OOM
        k8s_state = self._get_component_by_plugin(components, "kubernetes")

        if k8s_state and linux_state:
            k8s_issues = " ".join(k8s_state.issues or []).lower()
            linux_issues = " ".join(linux_state.issues or []).lower()
            if ("crashloop" in k8s_issues or "oomkilled" in k8s_issues) and (
                "oom" in linux_issues or "memory" in linux_issues
            ):
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="linux",
                        related=["kubernetes"],
                        evidence="K8s pods OOMKilled while host reports memory pressure — raise limits or add memory",
                    )
                )

        # Корреляция: Netdiag TLS expiry
        netdiag_state = self._get_component_by_plugin(components, "netdiag")

        if netdiag_state and nginx_state:
            netdiag_issues = " ".join(netdiag_state.issues or []).lower()
            if ("expir" in netdiag_issues or "certificate" in netdiag_issues) and nginx_state.status in [
                Status.DEGRADED, Status.CRITICAL,
            ]:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="netdiag",
                        related=["nginx"],
                        evidence="TLS certificate issue while Nginx is failing — check cert renewal",
                    )
                )

        # Корреляция: OOM events
        if linux_state and linux_state.status == Status.CRITICAL:
            issues_str = " ".join(linux_state.issues or [])
            if "oom" in issues_str.lower() or "killed" in issues_str.lower():
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="linux",
                        related=["docker", "nginx", "postgres"],
                        evidence="OOM killer detected on host — may have killed critical processes",
                    )
                )

        # Корреляция: Disk full + Docker (image/container disk usage)
        if linux_state and docker_state:
            linux_issues = " ".join(linux_state.issues or []).lower()
            if ("disk" in linux_issues or "no space" in linux_issues) and docker_state.status in [
                Status.DEGRADED, Status.CRITICAL,
            ]:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="linux",
                        related=["docker"],
                        evidence="Host disk pressure while Docker is degraded — check docker_system_df, images and volumes may have filled the disk",
                    )
                )

        # Корреляция: Memory pressure + PostgreSQL (shared buffers / work_mem)
        if linux_state and postgres_state:
            linux_issues = " ".join(linux_state.issues or []).lower()
            if ("memory" in linux_issues or "swap" in linux_issues) and postgres_state.status in [
                Status.DEGRADED, Status.CRITICAL,
            ]:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="linux",
                        related=["postgres"],
                        evidence="Host memory pressure while PostgreSQL is degraded — check work_mem, shared_buffers and pg_activity for memory-heavy queries",
                    )
                )

        # Корреляция: Nginx + PostgreSQL (upstream failures due to slow DB)
        if nginx_state and postgres_state:
            if nginx_state.status in [Status.DEGRADED, Status.CRITICAL] and postgres_state.status in [
                Status.DEGRADED, Status.CRITICAL,
            ]:
                correlations.append(
                    Correlation(
                        type="cascade",
                        source="postgres",
                        related=["nginx"],
                        evidence="PostgreSQL degraded while Nginx reports upstream failures/timeouts — slow DB queries likely cause 502/504 at the proxy",
                    )
                )

        
        return correlations
    
    def _get_component_by_plugin(
        self,
        components: list[ComponentState],
        plugin_id: str,
    ) -> ComponentState | None:
        """Найти компонент по plugin_id"""
        for c in components:
            if c.plugin_id == plugin_id:
                return c
        return None
    
    def get_overall_status(self) -> Status:
        """Общий статус системы (худший из статусов компонентов)"""
        status_priority = {
            Status.CRITICAL: 4,
            Status.ERROR: 3,
            Status.DEGRADED: 2,
            Status.UNKNOWN: 1,
            Status.HEALTHY: 0,
        }
        
        max_status = Status.UNKNOWN
        max_priority = -1
        
        for component in self._components.values():
            priority = status_priority.get(component.status, -1)
            if priority > max_priority:
                max_priority = priority
                max_status = component.status
        
        return max_status

    def get_summary(self) -> dict[str, Any]:
        """Сводка по всем компонентам
        
        Returns:
            Словарь со статусами по каждому компоненту и общим статусом
        """
        components = self.get_components()
        
        summary = {
            "total_components": len(components),
            "healthy": 0,
            "degraded": 0,
            "critical": 0,
            "error": 0,
            "unknown": 0,
            "components": [],
            "overall_status": self.get_overall_status().value,
        }
        
        for comp in components:
            status_key = comp.status.value
            if status_key in summary:
                summary[status_key] += 1
            summary["components"].append({
                "plugin_id": comp.plugin_id,
                "status": comp.status.value,
                "last_checked": comp.last_checked,
                "issues": comp.issues or [],
            })
        
        return summary
