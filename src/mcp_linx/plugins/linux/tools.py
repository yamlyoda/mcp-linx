"""Инструменты Linux плагина"""

from __future__ import annotations

import re
import shlex
from typing import Any

from mcp_linx.plugins.linux import LinuxPlugin
from mcp_linx.types import ToolResult

# Ограниченный список разрешённых log_type для /var/log/ (защита от path traversal)
_ALLOWED_LOG_FILES = {
    "dpkg.log",
    "syslog",
    "messages",
    "kern.log",
    "auth.log",
    "user.log",
    "boot.log",
    "cron.log",
    "faillog",
    "wtmp",
    "btmp",
    "dmesg",
    "lastlog",
}

_FILE_UNIT_RE = re.compile(r"^[A-Za-z0-9@:_.\-]+\.(service|socket|timer|target|mount|device)$")
_FILE_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")


async def linux_logs(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Чтение системных логов"""
    host = params.get("host")
    log_type = params.get("log_type", "syslog")
    lines = min(int(params.get("lines", 100)), 500)
    since = params.get("since")
    priority = params.get("priority", "info")

    if log_type == "journal":
        since_flag = f"--since={shlex.quote(since)}" if since else ""
        priority_flag = f"-p {shlex.quote(priority)}" if priority else ""
        command = f"journalctl {since_flag} {priority_flag} -n {lines}"
    elif log_type == "auth":
        command = f"tail -n {lines} /var/log/auth.log"
    elif log_type == "kern":
        command = f"tail -n {lines} /var/log/kern.log"
    elif log_type == "syslog" or log_type == "messages":
        command = f"tail -n {lines} /var/log/syslog"
    elif log_type in _ALLOWED_LOG_FILES:
        # Только из белого списка — нельзя выйти за пределы /var/log/
        command = f"tail -n {lines} /var/log/{log_type}"
    else:
        return ToolResult.error(
            f"Invalid log_type '{log_type}'. Allowed: journal, auth, kern, syslog, messages, "
            f"{', '.join(sorted(_ALLOWED_LOG_FILES))}"
        )

    result = await plugin._run_command(command, host=host)

    if result["returncode"] != 0:
        return ToolResult.error(f"Failed to read logs: {result['stderr']}")

    log_lines = result["stdout"].split("\n")

    error_count = sum(
        1
        for line in log_lines
        if any(kw in line.lower() for kw in ["error", "fail", "fatal", "critical"])
    )
    warning_count = sum(
        1 for line in log_lines if any(kw in line.lower() for kw in ["warn", "warning"])
    )

    return ToolResult.ok(
        {
            "logs": result["stdout"],
            "lines": len(log_lines),
            "analysis": {
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": len(log_lines) - error_count - warning_count,
            },
        }
    )


async def linux_network(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Сетевые интерфейсы, порты, соединения"""
    host = params.get("host")
    results: dict[str, Any] = {}

    interface_result = await plugin._run_command("ip -br addr", host=host)
    results["interfaces"] = interface_result.get("stdout", "Unable to get interfaces")

    ss_result = await plugin._run_command("ss -tuln", host=host)
    results["listening_ports"] = ss_result.get("stdout", "Unable to get listening ports")

    conn_result = await plugin._run_command("ss -tan", host=host)
    results["connections"] = conn_result.get("stdout", "")

    route_result = await plugin._run_command("ip route show", host=host)
    results["routes"] = route_result.get("stdout", "")

    dns_result = await plugin._run_command(
        "cat /etc/resolv.conf 2>/dev/null || echo 'No resolv.conf'", host=host
    )
    results["dns"] = dns_result.get("stdout", "")

    return ToolResult.ok(results)


async def linux_firewall(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Firewall snapshot: nftables + iptables + policy routing (read-only).

    Закрывает слепую зону INCIDENT_504: `iptables -L` не показывает
    nft-правила (skuid → fwmark) и blackhole-таблицы. Собирает:
    nft ruleset, ip rule, все таблицы маршрутов, ufw status (best-effort).
    Только чтение: nft list / ip route show / iptables -S.
    """
    host = params.get("host")
    import re as _re

    results: dict[str, Any] = {}
    issues: list[str] = []

    # 1. nftables ruleset (read-only: только list)
    nft = await plugin._run_command("nft list ruleset 2>&1 || echo 'NO_NFT'", host=host)
    nft_text = nft.get("stdout", "")
    results["nft_ruleset"] = nft_text[:6000]
    results["nft_available"] = "NO_NFT" not in nft_text

    # Парсинг маркировок: meta skuid ... tcp dport X ... mark set Y
    marks: list[dict[str, Any]] = []
    for ln in nft_text.splitlines():
        if "mark set" in ln:
            m = _re.search(
                r"skuid\s+[\"']?(\S+?)[\"']?\s+.*?dport\s+(\d+).*?mark\s+set\s+(0x[0-9a-fA-F]+|\d+)",
                ln,
            )
            if m:
                marks.append(
                    {
                        "skuid": m.group(1),
                        "dport": int(m.group(2)),
                        "mark": m.group(3),
                        "rule": ln.strip()[:200],
                    }
                )
            else:
                m2 = _re.search(r"mark\s+set\s+(0x[0-9a-fA-F]+|\d+)", ln)
                if m2:
                    marks.append({"mark": m2.group(1), "rule": ln.strip()[:200]})
    results["marks"] = marks
    if marks:
        issues.append(f"nft маркировки fwmark: {len(marks)} правил — проверьте ip rule/table ниже")

    # 2. Policy routing: ip rule + все таблицы
    rule = await plugin._run_command("ip rule show 2>&1", host=host)
    rule_text = rule.get("stdout", "")
    results["ip_rules"] = rule_text[:2000]

    policy_routes: list[dict[str, Any]] = []
    tables: set[str] = set(_re.findall(r"lookup\s+(\S+)", rule_text))
    tables.update(["main", "local"])
    for tbl in sorted(tables)[:10]:
        r = await plugin._run_command(f"ip route show table {tbl} 2>&1", host=host)
        out = r.get("stdout", "").strip()
        if out and "Error" not in out:
            policy_routes.append({"table": tbl, "routes": out[:1500]})
            if "blackhole" in out.lower():
                issues.append(
                    f"Table {tbl} содержит blackhole — трафик с fwmark туда уходит в никуда"
                )
    results["policy_routes"] = policy_routes

    # 3. iptables fallback (read-only: -S/-L без изменений)
    ipt = await plugin._run_command("iptables -S 2>&1 | head -50 || echo 'NO_IPTABLES'", host=host)
    results["iptables"] = ipt.get("stdout", "")[:3000]

    # 4. ufw status (best-effort)
    ufw = await plugin._run_command("ufw status verbose 2>&1 || echo 'NO_UFW'", host=host)
    results["ufw"] = ufw.get("stdout", "")[:1500]

    # 5. Опционально: ip route get для пары src->dst
    probe_dst = str(params.get("probe_dst", "")).strip()
    if probe_dst:
        if not _re.match(r"^[A-Za-z0-9.\-:]+$", probe_dst):
            return ToolResult.error(f"Invalid probe_dst '{probe_dst}'")
        g = await plugin._run_command(f"ip route get {probe_dst} 2>&1", host=host)
        results["route_get"] = {probe_dst: g.get("stdout", "").strip()[:500]}

    if issues:
        return ToolResult.degraded(results, issues)
    return ToolResult.ok(results)


async def linux_disk(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Использование диска и файловых систем"""
    host = params.get("host")
    results: dict[str, Any] = {}

    df_result = await plugin._run_command("df -h", host=host)
    if df_result["returncode"] == 0:
        results["disk_usage"] = df_result["stdout"]

    inode_result = await plugin._run_command("df -i", host=host)
    if inode_result["returncode"] == 0:
        results["inode_usage"] = inode_result["stdout"]

    lsblk_result = await plugin._run_command("lsblk -o NAME,SIZE,TYPE,MOUNTPOINT", host=host)
    if lsblk_result["returncode"] == 0:
        results["block_devices"] = lsblk_result["stdout"]

    swap_result = await plugin._run_command(
        "free -h; swapon --show 2>/dev/null || echo 'No swap'", host=host
    )
    if swap_result["returncode"] == 0:
        results["swap"] = swap_result["stdout"]

    vm_result = await plugin._run_command("vmstat -s", host=host)
    if vm_result["returncode"] == 0:
        results["vm_stats"] = vm_result["stdout"]

    return ToolResult.ok(results)


async def linux_memory(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Подробная информация о памяти"""
    host = params.get("host")
    results: dict[str, Any] = {}

    free_result = await plugin._run_command("free -h", host=host)
    if free_result["returncode"] == 0:
        results["memory"] = free_result["stdout"]

    vm_stat_result = await plugin._run_command("vmstat -s", host=host)
    if vm_stat_result["returncode"] == 0:
        results["vm_stats"] = vm_stat_result["stdout"]

    swap_result = await plugin._run_command(
        "swapon --show 2>/dev/null || echo 'No swap'", host=host
    )
    if swap_result["returncode"] == 0:
        results["swap"] = swap_result["stdout"]

    return ToolResult.ok(results)


async def linux_host_stats(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Получение статистики хоста: CPU, память, диск, загрузка"""
    host = params.get("host")
    import platform
    import sys

    is_macos = sys.platform == "darwin"
    commands = {
        "kernel": "uname -a",
        "uptime": "uptime",
        "memory": "vm_stat | head -20" if is_macos else "free -h",
        "load": "sysctl -n vm.loadavg" if is_macos else "cat /proc/loadavg",
        "cpu_count": "sysctl -n hw.ncpu" if is_macos else "nproc",
        "cpu_model": "sysctl -n machdep.cpu.brand_string"
        if is_macos
        else "cat /proc/cpuinfo | grep 'model name' | head -1",
    }

    results: dict[str, str] = {}
    for key, command in commands.items():
        try:
            result = await plugin._run_command(command, host=host)
            if result["returncode"] == 0 and result["stdout"].strip():
                results[key] = result["stdout"].strip()
            else:
                err = result["stderr"].strip() or "empty output"
                results[key] = f"Error: {err}"
        except Exception as e:
            results[key] = f"Error: {e}"

    return ToolResult.ok(
        {
            "kernel": results.get("kernel", ""),
            "uptime": results.get("uptime", ""),
            "memory": results.get("memory", ""),
            "load_avg": results.get("load", ""),
            "cpu_count": results.get("cpu_count", ""),
            "cpu_model": results.get("cpu_model", ""),
            "platform": platform.platform(),
        }
    )


async def linux_processes(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Список запущенных процессов с фильтрацией"""
    host = params.get("host")
    limit = min(int(params.get("limit", 50)), 100)
    filter_str = params.get("filter", "")

    if filter_str:
        safe_filter = shlex.quote(filter_str)
        command = f"ps aux | grep -i {safe_filter} | head -{limit}"
    else:
        # macOS ps без --sort; head берёт с запасом под header
        command = f"ps aux | head -{limit + 1}"

    result = await plugin._run_command(command, host=host)

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
            processes.append(
                {
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
                }
            )

    return ToolResult.ok(
        {
            "processes": processes,
            "count": len(processes),
        }
    )


async def linux_execute_command(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Выполнение произвольной read-only команды"""
    host = params.get("host")
    command = params.get("command", "")
    timeout = int(params.get("timeout", 30))

    if not command:
        return ToolResult.error("Command is required")

    result = await plugin._run_command(command, timeout, host=host)

    return ToolResult.ok(result)


async def linux_file_diagnostics(plugin: LinuxPlugin, params: dict[str, Any]) -> ToolResult:
    """Проверить путь, права, атрибуты и доступность записи к файлу.

    Все основные команды read-only. Проверка ``test -w`` от сервисного user
    выполняется только при ``plugins.linux.privileged_tools=true`` и через
    отдельный строгий runner; команда ``chattr`` намеренно не поддерживается.
    """
    host = params.get("host")
    path = str(params.get("path", "")).strip()
    unit = str(params.get("unit", "")).strip() or None
    user = str(params.get("user", "")).strip() or None

    if not path.startswith("/") or "\x00" in path or "\n" in path or "\r" in path:
        return ToolResult.error("Param 'path' must be an absolute path without NUL/newlines")
    if len(path) > 4096:
        return ToolResult.error("Param 'path' is too long")
    if unit and not _FILE_UNIT_RE.fullmatch(unit):
        return ToolResult.error("Param 'unit' must be a valid systemd unit name")
    if user and not _FILE_USER_RE.fullmatch(user):
        return ToolResult.error("Param 'user' must be a valid local user name")
    try:
        timeout = max(2, min(int(params.get("timeout", 10)), 30))
    except (TypeError, ValueError):
        return ToolResult.error("Param 'timeout' must be an integer")

    quoted_path = shlex.quote(path)
    checks: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    commands = {
        "stat": f"stat -c '%a|%A|%U|%G|%u|%g|%s|%F' -- {quoted_path}",
        "namei": f"namei -l {quoted_path}",
        "attributes": f"lsattr -d -- {quoted_path}",
        "mount": f"findmnt -T {quoted_path} -o TARGET,SOURCE,FSTYPE,OPTIONS",
        "disk": f"df -h -- {quoted_path}",
    }
    for key, command in commands.items():
        result = await plugin._run_command(command, timeout=timeout, host=host)
        checks[key] = result
        if result.get("returncode", 1) != 0:
            errors.append(f"{key}: {result.get('stderr', '').strip() or 'command failed'}")

    stat_parts = checks["stat"].get("stdout", "").strip().split("|", 7)
    stat_data: dict[str, Any] = {"raw": checks["stat"].get("stdout", "").strip()}
    if len(stat_parts) == 8:
        stat_data.update(
            {
                "mode": stat_parts[0],
                "permissions": stat_parts[1],
                "owner": stat_parts[2],
                "group": stat_parts[3],
                "uid": stat_parts[4],
                "gid": stat_parts[5],
                "size": stat_parts[6],
                "type": stat_parts[7],
            }
        )

    attributes_raw = checks["attributes"].get("stdout", "").strip()
    attribute_token = attributes_raw.split()[0] if attributes_raw else ""
    immutable = bool(attribute_token and "i" in attribute_token)
    if immutable:
        errors.append("file has immutable attribute (i)")

    unit_properties: dict[str, str] = {}
    unit_data: dict[str, Any] | None = None
    if unit:
        unit_command = (
            f"systemctl show {shlex.quote(unit)} --no-pager "
            "-p User -p Group -p DynamicUser -p ProtectSystem -p ReadOnlyPaths "
            "-p ReadWritePaths -p InaccessiblePaths -p MainPID"
        )
        unit_result = await plugin._run_command(unit_command, timeout=timeout, host=host)
        unit_data = {"name": unit, "raw": unit_result.get("stdout", "").strip()}
        for line in unit_result.get("stdout", "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                unit_properties[key] = value
        unit_data["properties"] = unit_properties
        if unit_result.get("returncode", 1) != 0:
            errors.append(f"systemd: {unit_result.get('stderr', '').strip() or 'command failed'}")

    effective_user = user or (unit_properties.get("User") if unit_properties else None)
    write_check: dict[str, Any] = {"user": effective_user}
    if not effective_user:
        write_check.update(
            {
                "status": "skipped",
                "writable": None,
                "reason": "service user is unknown; pass user or unit",
            }
        )
    else:
        config = getattr(plugin, "_config", None) or {}
        if not bool(config.get("privileged_tools", False)):
            write_check.update(
                {
                    "status": "skipped",
                    "writable": None,
                    "reason": "set plugins.linux.privileged_tools=true to run test -w as user",
                }
            )
            errors.append("write check skipped: privileged_tools is disabled")
        else:
            command = f"runuser -u {shlex.quote(effective_user)} -- test -w {quoted_path}"
            try:
                write_result = await plugin._run_privileged(command, timeout, host=host)
            except Exception as e:
                write_result = {"stdout": "", "stderr": str(e), "returncode": 1}
            writable = write_result.get("returncode", 1) == 0
            write_check.update(
                {
                    "status": "ok" if writable else "error",
                    "writable": writable,
                    "returncode": write_result.get("returncode"),
                    "error": write_result.get("stderr", "").strip()[:500],
                }
            )
            if not writable:
                errors.append(f"user {effective_user} cannot write to path")

    data = {
        "path": path,
        "file_exists": checks["stat"].get("returncode", 1) == 0,
        "stat": stat_data,
        "path_chain": checks["namei"].get("stdout", ""),
        "attributes": {"raw": attributes_raw, "immutable": immutable},
        "filesystem": {
            "mount": checks["mount"].get("stdout", ""),
            "disk": checks["disk"].get("stdout", ""),
        },
        "systemd": unit_data,
        "write_check": write_check,
        "errors": errors,
    }
    if errors:
        return ToolResult.degraded(data, errors)
    return ToolResult.ok(data)
