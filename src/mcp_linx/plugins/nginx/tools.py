
"""Инструменты Nginx плагина - Часть 2: config, upstream"""

from __future__ import annotations

from typing import Any

from mcp_linx.plugins.nginx import NginxPlugin
from mcp_linx.types import ToolResult


async def nginx_config(plugin: NginxPlugin, params: dict[str, Any]) -> ToolResult:
    """Проверка конфигурации Nginx"""
    results: dict[str, Any] = {}
    
    # Тест конфигурации
    test_result = await plugin._run_command("nginx -t 2>&1")
    results["config_test_output"] = test_result.get("stdout", test_result.get("stderr", ""))
    results["config_test_ok"] = test_result["returncode"] == 0
    
    # Основной конфиг
    conf_result = await plugin._run_command("grep -v '^#' /etc/nginx/nginx.conf | grep -v '^$' | head -50")
    results["main_config"] = conf_result.get("stdout", "Not found")
    
    # Сайты
    sites_result = await plugin._run_command("ls -la /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null || echo 'No sites configured'")
    results["sites"] = sites_result.get("stdout", "Not found")
    
    # SSL
    ssl_result = await plugin._run_command("grep -r 'ssl_certificate' /etc/nginx/ 2>/dev/null | head -10 || echo 'No SSL configured'")
    results["ssl"] = ssl_result.get("stdout", "Not found")
    
    # Worker settings
    worker_result = await plugin._run_command("grep -E 'worker_processes|worker_connections|worker_rlimit' /etc/nginx/nginx.conf 2>/dev/null || echo 'Not found'")
    results["worker_settings"] = worker_result.get("stdout", "Not found")
    
    return ToolResult.ok(results)


async def nginx_upstream(plugin: NginxPlugin, params: dict[str, Any]) -> ToolResult:
    """Статус upstream серверов"""
    results: dict[str, Any] = {}
    
    # Поиск upstream блоков
    upstream_result = await plugin._run_command(
        "grep -A 10 'upstream' /etc/nginx/nginx.conf /etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/*.conf 2>/dev/null | grep -v '^#' | head -100"
    )
    results["upstream_config"] = upstream_result.get("stdout", "No upstream configured")
    
    # stub_status если настроен
    stub_url = plugin._config.get("stub_status_url") if plugin._config else None
    if stub_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(stub_url)
                if resp.status_code == 200:
                    results["stub_status"] = resp.text
                    results["active_connections"] = next(
                        (l for l in resp.text.split("\n") if "Active connections" in l), ""
                    )
                else:
                    results["stub_status_error"] = f"HTTP {resp.status_code}"
        except Exception as e:
            results["stub_status_error"] = str(e)
    
    # Парсинг upstream серверов
    upstream_servers = []
    for line in upstream_result.get("stdout", "").split("\n"):
        if "server" in line and ":" in line:
            parts = line.strip().split()
            for part in parts:
                if part.startswith("server") and ":" in part:
                    server_addr = part.split(";")[0].replace("server", "").strip()
                    if server_addr:
                        upstream_servers.append(server_addr)
    
    results["upstream_servers"] = upstream_servers
    
    # Проверка доступности
    live_servers = []
    dead_servers = []
    for server in upstream_servers[:10]:
        check_result = await plugin._run_command(
            f"curl -s -o /dev/null -w '%{{http_code}}' --connect-timeout 2 {server}/ 2>/dev/null || echo 'unreachable'"
        )
        status = check_result.get("stdout", "").strip()
        if status and status not in ("000", "unreachable"):
            live_servers.append(server)
        else:
            dead_servers.append(server)
    
    results["live_servers"] = live_servers
    results["dead_servers"] = dead_servers
    
    return ToolResult.ok(results)


"""Инструменты Nginx плагина - Часть 1: status, logs"""

from __future__ import annotations

from typing import Any

from mcp_linx.plugins.nginx import NginxPlugin
from mcp_linx.types import ToolResult


async def nginx_status(plugin: NginxPlugin, params: dict[str, Any]) -> ToolResult:
    """Статус службы Nginx и процессов"""
    results: dict[str, Any] = {}
    
    # Статус службы
    systemctl_result = await plugin._run_command("systemctl status nginx --no-pager")
    results["systemctl_status"] = systemctl_result.get("stdout", "")
    results["systemctl_code"] = systemctl_result.get("returncode", -1)
    
    # Конфигурационный тест
    config_test_result = await plugin._run_command("nginx -t 2>&1")
    results["config_test"] = config_test_result.get("stdout", config_test_result.get("stderr", ""))
    results["config_test_ok"] = config_test_result["returncode"] == 0
    
    # Версия
    version_result = await plugin._run_command("nginx -v 2>&1")
    results["version"] = version_result.get("stderr", version_result.get("stdout", ""))
    
    # Работающие процессы
    ps_result = await plugin._run_command("ps aux | grep '[n]ginx'")
    results["processes"] = ps_result.get("stdout", "")
    results["process_count"] = ps_result.get("stdout", "").count("\n")
    
    # Конфигурация worker_processes
    worker_result = await plugin._run_command("grep -E 'worker_processes|worker_connections' /etc/nginx/nginx.conf 2>/dev/null || echo 'Config not found'")
    results["worker_config"] = worker_result.get("stdout", "Not found")
    
    return ToolResult.ok(results)


async def nginx_logs(plugin: NginxPlugin, params: dict[str, Any]) -> ToolResult:
    """Чтение error и access логов Nginx"""
    log_type = params.get("log_type", "error")
    lines = min(int(params.get("lines", 100)), 500)
    
    config_path = plugin._config.get("log_path", "/var/log/nginx") if plugin._config else "/var/log/nginx"
    access_log = plugin._config.get("access_log", "access.log") if plugin._config else "access.log"
    error_log = plugin._config.get("error_log", "error.log") if plugin._config else "error.log"
    
    if log_type == "error":
        log_file = f"{config_path}/{error_log}"
    elif log_type == "access":
        log_file = f"{config_path}/{access_log}"
    elif log_type == "error_full":
        log_file = f"{config_path}/{error_log}"
    elif log_type == "access_full":
        log_file = f"{config_path}/{access_log}"
    else:
        log_file = f"{config_path}/{log_type}"
    
    command = f"tail -n {lines} {log_file}"
    result = await plugin._run_command(command)
    
    if result["returncode"] != 0:
        return ToolResult.error(f"Failed to read logs: {result['stderr']}")
    
    log_lines = result["stdout"].split("\n")
    
    # Анализ логов
    if log_type in ["error", "error_full"]:
        error_count = sum(1 for line in log_lines if any(kw in line.lower() for kw in ["error", "fail", "critical"]))
        timeout_count = sum(1 for line in log_lines if "timeout" in line.lower())
        refused_count = sum(1 for line in log_lines if "connection refused" in line.lower())
        
        return ToolResult.ok({
            "logs": result["stdout"],
            "lines": len(log_lines),
            "analysis": {
                "error_count": error_count,
                "timeout_count": timeout_count,
                "connection_refused_count": refused_count,
                "upstream_errors": timeout_count + refused_count,
            },
        })
    else:
        # Access log analysis
        status_2xx = sum(1 for line in log_lines if " 2" in line)
        status_3xx = sum(1 for line in log_lines if " 3" in line)
        status_4xx = sum(1 for line in log_lines if " 4" in line)
        status_5xx = sum(1 for line in log_lines if " 5" in line)
        
        return ToolResult.ok({
            "logs": result["stdout"],
            "lines": len(log_lines),
            "analysis": {
                "status_2xx": status_2xx,
                "status_3xx": status_3xx,
                "status_4xx": status_4xx,
                "status_5xx": status_5xx,
            },
        })
