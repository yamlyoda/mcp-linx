"""Инструменты Linux плагина"""

from __future__ import annotations

from typing import Any

from mcp_linx.plugins.linux import LinuxPlugin
from mcp_linx.types import ToolResult


async def linux_logs(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Чтение системных логов"""
    log_type = params.get("log_type", "syslog")
    lines = min(int(params.get("lines", 100)), 500)
    since = params.get("since")
    priority = params.get("priority", "info")
    
    if log_type == "journal":
        since_flag = f"--since='{since}'" if since else ""
        priority_flag = f"-p {priority}" if priority else ""
        command = f"journalctl {since_flag} {priority_flag} -n {lines}"
    elif log_type == "auth":
        command = f"tail -n {lines} /var/log/auth.log"
    elif log_type == "kern":
        command = f"tail -n {lines} /var/log/kern.log"
    elif log_type == "syslog" or log_type == "messages":
        command = f"tail -n {lines} /var/log/syslog"
    else:
        command = f"tail -n {lines} /var/log/{log_type}"
    
    result = await plugin._run_command(command)
    
    if result["returncode"] != 0:
        return ToolResult.error(f"Failed to read logs: {result['stderr']}")
    
    log_lines = result["stdout"].split("\n")
    
    # Анализ логов
    error_count = sum(1 for line in log_lines if any(kw in line.lower() for kw in ["error", "fail", "fatal", "critical"]))
    warning_count = sum(1 for line in log_lines if any(kw in line.lower() for kw in ["warn", "warning"]))
    
    return ToolResult.ok({
        "logs": result["stdout"],
        "lines": len(log_lines),
        "analysis": {
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": len(log_lines) - error_count - warning_count,
        },
    })




async def linux_network(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Сетевые интерфейсы, порты, соединения"""
    results: dict[str, Any] = {}
    
    interface_result = await plugin._run_command("ip -br addr")
    results["interfaces"] = interface_result.get("stdout", "Unable to get interfaces")
    
    ss_result = await plugin._run_command("ss -tuln")
    results["listening_ports"] = ss_result.get("stdout", "Unable to get listening ports")
    
    conn_result = await plugin._run_command("ss -tan")
    results["connections"] = conn_result.get("stdout", "")
    
    route_result = await plugin._run_command("ip route show")
    results["routes"] = route_result.get("stdout", "")
    
    dns_result = await plugin._run_command("cat /etc/resolv.conf 2>/dev/null || echo 'No resolv.conf'")
    results["dns"] = dns_result.get("stdout", "")
    
    return ToolResult.ok(results)




async def linux_disk(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Использование диска и файловых систем"""
    results: dict[str, Any] = {}
    
    df_result = await plugin._run_command("df -h")
    if df_result["returncode"] == 0:
        results["disk_usage"] = df_result["stdout"]
    
    inode_result = await plugin._run_command("df -i")
    if inode_result["returncode"] == 0:
        results["inode_usage"] = inode_result["stdout"]
    
    lsblk_result = await plugin._run_command("lsblk -o NAME,SIZE,TYPE,MOUNTPOINT")
    if lsblk_result["returncode"] == 0:
        results["block_devices"] = lsblk_result["stdout"]
    
    path = params.get("path", "/")
    du_result = await plugin._run_command(f"du -sh {path} 2>/dev/null || echo 'Cannot access {path}'")
    results[f"du_{path}"] = du_result.get("stdout", "").strip()
    
    return ToolResult.ok(results)




async def linux_memory(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Детальная информация об использовании памяти"""
    results: dict[str, Any] = {}
    
    free_result = await plugin._run_command("free -h")
    if free_result["returncode"] == 0:
        results["free"] = free_result["stdout"]
    
    meminfo_result = await plugin._run_command("cat /proc/meminfo")
    if meminfo_result["returncode"] == 0:
        results["meminfo"] = meminfo_result["stdout"]
    
    swap_result = await plugin._run_command("swapon --show")
    if swap_result["returncode"] == 0:
        results["swap"] = swap_result["stdout"]
    
    vm_result = await plugin._run_command("vmstat -s")
    if vm_result["returncode"] == 0:
        results["vm_stats"] = vm_result["stdout"]
    
    return ToolResult.ok(results)




async def linux_execute_command(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Выполнение произвольной read-only команды"""
    command = params.get("command", "")
    timeout = int(params.get("timeout", 30))
    
    if not command:
        return ToolResult.error("Command is required")
    
    result = await plugin._run_command(command, timeout)
    
    return ToolResult.ok(result)

"""Инструменты Linux плагина - Часть 1: host_stats и processes"""

from mcp_linx.types import ToolResult




async def linux_host_stats(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Получение статистики хоста: CPU, память, диск, загрузка"""
    commands = [
        ("uname -a", "kernel"),
        ("uptime", "uptime"),
        ("free -h", "memory"),
        ("cat /proc/loadavg", "load"),
        ("nproc", "cpu_count"),
        ("cat /proc/cpuinfo | grep 'model name' | head -1", "cpu_model"),
    ]
    
    results: dict[str, str] = {}
    for command, key in commands:
        try:
            result = await plugin._run_command(command)
            if result["returncode"] == 0:
                results[key] = result["stdout"].strip()
            else:
                results[key] = f"Error: {result['stderr'].strip()}"
        except Exception as e:
            results[key] = f"Error: {e}"
    
    return ToolResult.ok({
        "kernel": results.get("kernel", ""),
        "uptime": results.get("uptime", ""),
        "memory": results.get("memory", ""),
        "load_avg": results.get("load", ""),
        "cpu_count": results.get("cpu_count", ""),
        "cpu_model": results.get("cpu_model", ""),
    })




async def linux_processes(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Список запущенных процессов с фильтрацией"""
    limit = min(int(params.get("limit", 50)), 100)
    filter_str = params.get("filter", "")
    
    if filter_str:
        command = f"ps aux | grep -i '{filter_str}' | head -{limit}"
    else:
        command = f"ps aux --sort=-%cpu | head -{limit + 1}"
    
    result = await plugin._run_command(command)
    
    if result["returncode"] != 0:
        return ToolResult.error(f"Failed to get processes: {result['stderr']}")
    
    lines = result["stdout"].strip().split("\n")
    if len(lines) < 2:
        return ToolResult.ok({"processes": [], "count": 0})
    
    processes = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(None, 10)
        if len(parts) >= 11:
            processes.append({
                "user": parts[0],
                "pid": parts[1],
                "cpu_percent": parts[2],
                "memory_percent": parts[3],
                "vsz": parts[4],
                "rss": parts[5],
                "tty": parts[6],
                "stat": parts[7],
                "start": parts[8],
                "time": parts[9],
                "command": parts[10],
            })
    
    return ToolResult.ok({
        "processes": processes,
        "count": len(processes),
    })

