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

        
        # Корреляция: OOM → container restart → Nginx 5xx (тройная цепочка)
        if linux_state and docker_state and nginx_state:
            linux_issues = " ".join(linux_state.issues or []).lower()
            docker_issues = " ".join(docker_state.issues or []).lower()
            nginx_bad = nginx_state.status in [Status.DEGRADED, Status.CRITICAL]
            if ("oom" in linux_issues or "killed" in linux_issues) and (
                "restart" in docker_issues or "exit" in docker_issues or "crash" in docker_issues
            ) and nginx_bad:
                correlations.append(
                    Correlation(
                        type="cascade",
                        source="linux",
                        related=["docker", "nginx"],
                        evidence="OOM killer → container restart → Nginx 5xx: host memory pressure likely killed the container, check maxmemory/limits",
                    )
                )

        # Корреляция: PostgreSQL idle-in-transaction (locks/connections)
        if postgres_state:
            pg_issues = " ".join(postgres_state.issues or []).lower()
            if any(kw in pg_issues for kw in ["idle", "lock", "blocked", "long-running"]):
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="postgres",
                        related=["postgres"],
                        evidence="PostgreSQL reports idle-in-transaction/locks — check pg_activity for 'idle in transaction' sessions and pg_locks for blockers",
                    )
                )

        # Корреляция: PostgreSQL replication lag → slow reads
        if postgres_state and nginx_state:
            pg_issues = " ".join(postgres_state.issues or []).lower()
            if "replicat" in pg_issues and ("lag" in pg_issues or "delay" in pg_issues) and \
                    nginx_state.status in [Status.DEGRADED, Status.CRITICAL]:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="postgres",
                        related=["nginx"],
                        evidence="PostgreSQL replication lag detected while Nginx is degraded — read replicas may serve stale data or time out",
                    )
                )

        # Корреляция: Linux no-space → docker_prune рекомендован
        if linux_state and docker_state:
            linux_issues = " ".join(linux_state.issues or []).lower()
            if any(kw in linux_issues for kw in ["no space", "disk full", "disk is full"]):
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="linux",
                        related=["docker"],
                        evidence="Host reports no space left — recommend docker_system_df + docker_prune (dry-run) to reclaim space from images/volumes",
                    )
                )

        # Корреляция (INCIDENT_504): таймаут == proxy_connect_timeout → L3/L4 дроп
        # Подпись SYN-дропа, а не медленного кода: измеренное время совпадает
        # с proxy_connect_timeout из конфига nginx (±15%).
        if nginx_state:
            nx_issues = " ".join(nginx_state.issues or []).lower()
            nx_metrics = nginx_state.metrics or {}
            if "upstream timed out" in nx_issues or "timed out" in nx_issues:
                proxy_ct = nx_metrics.get("proxy_connect_timeout_s")
                measured = nx_metrics.get("upstream_connect_ms")
                match = False
                if isinstance(proxy_ct, (int, float)) and isinstance(measured, (int, float)) and proxy_ct > 0:
                    ratio = measured / 1000.0 / float(proxy_ct)
                    match = 0.85 <= ratio <= 1.15
                elif "timed out" in nx_issues:
                    match = True  # таймаут без замеров — всё равно L3/L4-подозрение
                if match:
                    correlations.append(
                        Correlation(
                            type="root_cause_suspected",
                            source="nginx",
                            related=["linux", "systemd", "netdiag"],
                            evidence="Upstream timeout совпадает с proxy_connect_timeout — "
                            "SYN дропается (firewall/nft/eBPF), а не медленный upstream. "
                            "Смотреть linux_firewall + service_ip_filter + tcp_connect_as",
                        )
                    )

        # Корреляция (INCIDENT_504): процесс может, сервис — нет → per-uid фильтр
        if netdiag_state := self._get_component_by_plugin(components, "netdiag"):
            nd_issues = " ".join(netdiag_state.issues or []).lower()
            if "per-uid" in nd_issues or "per-uid фильтр" in nd_issues:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="netdiag",
                        related=["linux", "systemd"],
                        evidence="TCP-проба проходит от одного пользователя и падает от сервисного "
                        "uid — per-uid фильтр (nft skuid / systemd IPAllow). "
                        "Смотреть linux_firewall (marks) + service_ip_filter",
                    )
                )

        # Корреляция (INCIDENT_504): DB_HOST vs listen_addresses mismatch
        if postgres_state:
            pg_issues = " ".join(postgres_state.issues or []).lower()
            if "db_host" in pg_issues and "listen" in pg_issues:
                correlations.append(
                    Correlation(
                        type="root_cause_suspected",
                        source="postgres",
                        related=["linux", "netdiag"],
                        evidence="DB_HOST из конфига приложения не совпадает с listen_addresses "
                        "PostgreSQL — не менять вслепую, сверить ss -tlnp + pg_hba.conf",
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
