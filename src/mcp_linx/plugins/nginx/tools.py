"""Инструменты Nginx плагина"""

from __future__ import annotations

import os
from typing import Any

from mcp_linx.plugins.nginx import NginxPlugin
from mcp_linx.types import ToolResult

# Разрешённые директории логов (защита от path traversal через конфиг)
_ALLOWED_LOG_DIRS = {"/var/log/nginx", "/usr/local/nginx/logs", "/var/log"}

# Разрешённые имена лог-файлов (basename без путей и "..")
_ALLOWED_LOG_NAMES = {"access.log", "error.log"}


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
    """Статус upstream серверов: конфиг + реальный HTTP health check.

    По умолчанию выполняет GET к каждому upstream-адресу (httpx, таймаут timeout).
    Добавляет схему http://, если не указана. unix-сокеты пропускаются (недоступны по HTTP).
    """
    import httpx

    timeout = max(1, min(int(params.get("timeout", 3)), 30))
    max_servers = max(1, min(int(params.get("max_servers", 10)), 50))

    results: dict[str, Any] = {}

    # --- 0. proxy_* таймауты из конфига (для корреляции timeout==proxy_connect_timeout) ---
    import re as _re
    import time as _time

    proxy_ct_s: float | None = None
    proxy_rt_s: float | None = None
    try:
        to_result = await plugin._run_command(
            "grep -rE 'proxy_(connect|read|send)_timeout' /etc/nginx/nginx.conf "
            "/etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/*.conf "
            "2>/dev/null | head -20"
        )
        to_text = to_result.get("stdout", "")
        results["proxy_timeout_config"] = to_text.strip()[:1000]

        def _parse_timeout(text: str, name: str) -> float | None:
            m = _re.search(rf"{name}\s+([\d.]+)\s*(ms|s|m)?", text)
            if not m:
                return None
            val = float(m.group(1))
            unit = (m.group(2) or "s").lower()
            return val / 1000.0 if unit == "ms" else (val * 60.0 if unit == "m" else val)

        # Берём последнее значение (nginx: последний в контексте побеждает)
        for ln in to_text.splitlines():
            if "proxy_connect_timeout" in ln:
                v = _parse_timeout(ln, "proxy_connect_timeout")
                if v is not None:
                    proxy_ct_s = v
            if "proxy_read_timeout" in ln:
                v = _parse_timeout(ln, "proxy_read_timeout")
                if v is not None:
                    proxy_rt_s = v
    except Exception:
        pass
    if proxy_ct_s is not None:
        results["proxy_connect_timeout_s"] = proxy_ct_s
    if proxy_rt_s is not None:
        results["proxy_read_timeout_s"] = proxy_rt_s

    # --- 1. Поиск upstream блоков в конфиге ---
    upstream_result = await plugin._run_command(
        "grep -A 10 'upstream' /etc/nginx/nginx.conf /etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/*.conf 2>/dev/null | grep -v '^#' | head -100"
    )
    results["upstream_config"] = upstream_result.get("stdout", "No upstream configured")

    # --- 2. Парсинг адресов серверов ---
    upstream_servers: list[str] = []
    for line in upstream_result.get("stdout", "").split("\n"):
        line = line.strip()
        # строка вида: "server 127.0.0.1:3000 weight=1;" или "server backend:8080;"
        if not line.startswith("server"):
            continue
        tokens = line[len("server"):].split()
        if not tokens:
            continue
        addr = tokens[0].rstrip(";,").strip()
        if addr and addr not in upstream_servers:
            upstream_servers.append(addr)

    results["upstream_servers"] = upstream_servers[:max_servers]

    # --- 3. Реальный HTTP health check ---
    checks: list[dict[str, Any]] = []
    live: list[str] = []
    dead: list[str] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for server in upstream_servers[:max_servers]:
            # unix:/path — недоступен по HTTP, только skip
            if server.startswith("unix:"):
                checks.append({
                    "server": server,
                    "type": "socket",
                    "status": "skipped",
                    "note": "unix-socket: HTTP health check not applicable",
                })
                continue

            # нормализуем URL
            url = server
            if not url.startswith(("http://", "https://")):
                host_part = url.split("/")[0]
                url = f"http://{host_part}"

            try:
                _t0 = _time.monotonic()
                resp = await client.get(url)
                connect_ms = round((_time.monotonic() - _t0) * 1000, 1)
                ok = resp.status_code < 500  # 4xx = жив, 5xx = жив но ошибается
                entry: dict[str, Any] = {
                    "server": server,
                    "url": url,
                    "status_code": resp.status_code,
                    "alive": ok,
                    "connect_ms": connect_ms,
                }
                if ok:
                    live.append(server)
                else:
                    dead.append(server)
                    entry["note"] = f"HTTP {resp.status_code} (5xx)"
            except Exception as e:
                dead.append(server)
                entry = {
                    "server": server,
                    "url": url,
                    "alive": False,
                    "error": str(e)[:200],
                }
                # Таймаут httpx ≈ proxy_connect_timeout → подпись SYN-дропа (INCIDENT_504)
                if proxy_ct_s and ("timeout" in str(e).lower() or "timed out" in str(e).lower()):
                    entry["matches_proxy_connect_timeout"] = True
            checks.append(entry)

    results["checks"] = checks
    results["live_servers"] = live
    results["dead_servers"] = dead

    if dead:
        return ToolResult.degraded(results, [f"Dead servers: {', '.join(dead)}"])
    return ToolResult.ok(results)



async def nginx_stub_status(plugin: NginxPlugin, params: dict[str, Any]) -> ToolResult:
    """HTTP-проверка stub_status: active connections, requests, reading/writing/waiting

    Требует настройки stub_status_url в конфиге плагина.
    """
    import httpx

    stub_url = plugin._config.get("stub_status_url") if plugin._config else None
    if not stub_url:
        return ToolResult.error(
            "stub_status_url is not configured. Add it to config/settings.yaml "
            "(plugins.nginx.stub_status_url, e.g. http://127.0.0.1/nginx_status)"
        )

    timeout = max(2, min(int(params.get("timeout", 5)), 30))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(str(stub_url))
    except Exception as e:
        return ToolResult.error(f"stub_status request failed: {e}")

    if resp.status_code != 200:
        return ToolResult.error(f"stub_status returned HTTP {resp.status_code}")

    text = resp.text
    data: dict[str, Any] = {"url": str(stub_url), "raw": text}
    issues: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Active connections"):
            try:
                data["active_connections"] = int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.lower().startswith("reading"):
            # Формат: "Reading: 0 Writing: 1 Waiting: 4"
            import re as _re
            for key in ("reading", "writing", "waiting"):
                m = _re.search(rf"{key}:\s*(\d+)", line, _re.IGNORECASE)
                if m:
                    data[key] = int(m.group(1))
        else:
            # Формат строки счётчиков: " 1234 1234 5678" (accepts handled requests)
            parts = line.split()
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                data["accepted"], data["handled"], data["requests"] = (
                    int(parts[0]), int(parts[1]), int(parts[2]),
                )

    if isinstance(data.get("active_connections"), int):
        if data["active_connections"] > 5000:
            issues.append(
                f"High connection count: {data['active_connections']} — "
                "check worker_connections limit"
            )
        if isinstance(data.get("reading"), int) and data["reading"] > 100:
            issues.append(f"High reading count: {data['reading']} — slow clients or upstream")

    if issues:
        return ToolResult.degraded(data, issues)
    return ToolResult.ok(data)



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

    # Валидация config_path (только разрешённые директории)
    if config_path not in _ALLOWED_LOG_DIRS:
        return ToolResult.error(
            f"Invalid log_path '{config_path}'. Allowed: {', '.join(sorted(_ALLOWED_LOG_DIRS))}"
        )

    # Валидация имён лог-файлов (basename без путей и "..")
    for name, value in [("access_log", access_log), ("error_log", error_log)]:
        if not value or value != os.path.basename(value) or ".." in value:
            return ToolResult.error(
                f"Invalid {name} '{value}'. Must be a basename without path separators"
            )

    if log_type == "error":
        log_file = f"{config_path}/{error_log}"
    elif log_type == "access":
        log_file = f"{config_path}/{access_log}"
    elif log_type == "error_full":
        log_file = f"{config_path}/{error_log}"
    elif log_type == "access_full":
        log_file = f"{config_path}/{access_log}"
    else:
        return ToolResult.error(f"Invalid log_type '{log_type}'. Allowed: error, access, error_full, access_full")

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

