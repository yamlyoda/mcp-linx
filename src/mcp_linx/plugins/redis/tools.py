"""Tools Redis плагина: ping, info, clients"""

from __future__ import annotations

from typing import Any

from mcp_linx.types import Status, ToolResult

_ALLOWED_INFO_SECTIONS = {"memory", "clients", "stats", "replication", "persistence", "server"}


def _parse_info(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


async def redis_ping(plugin, params: dict[str, Any]) -> ToolResult:
    """Проверка доступности Redis"""
    try:
        result = await plugin._run_redis_cli("PING", timeout=10)
        if result["returncode"] == 0 and "PONG" in result["stdout"]:
            return ToolResult.ok({"reachable": True, "response": result["stdout"].strip()})
        return ToolResult(
            status=Status.UNHEALTHY,
            data={"reachable": False},
            error_message=result["stderr"][:500] or result["stdout"][:500],
        )
    except Exception as e:
        return ToolResult.error(str(e))


async def redis_info(plugin, params: dict[str, Any]) -> ToolResult:
    """INFO section: memory/clients/stats/replication/persistence/server"""
    section = str(params.get("section", "memory"))
    if section not in _ALLOWED_INFO_SECTIONS:
        return ToolResult.error(
            f"Unknown section '{section}'. Allowed: {sorted(_ALLOWED_INFO_SECTIONS)}"
        )
    try:
        result = await plugin._run_redis_cli(f"INFO {section}", timeout=15)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "redis-cli INFO failed")
        info = _parse_info(result["stdout"])
        return ToolResult.ok({"section": section, "info": info})
    except Exception as e:
        return ToolResult.error(str(e))


async def redis_clients(plugin, params: dict[str, Any]) -> ToolResult:
    """CLIENT LIST — список подключений"""
    try:
        limit = max(1, min(int(params.get("limit", 50)), 500))
        result = await plugin._run_redis_cli("CLIENT LIST", timeout=15)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "CLIENT LIST failed")
        lines = [ln for ln in result["stdout"].splitlines() if ln.strip()]
        clients = []
        for ln in lines[:limit]:
            fields: dict[str, str] = {}
            for token in ln.split():
                if "=" in token:
                    k, v = token.split("=", 1)
                    fields[k] = v
            clients.append(
                {
                    "id": fields.get("id", ""),
                    "addr": fields.get("addr", ""),
                    "name": fields.get("name", ""),
                    "age": fields.get("age", ""),
                    "idle": fields.get("idle", ""),
                    "cmd": fields.get("cmd", ""),
                    "db": fields.get("db", ""),
                }
            )
        blocked_cmds = {"blpop", "brpop", "blmove", "bzpopmin", "bzpopmax"}
        blocked = sum(1 for c in clients if c["cmd"] in blocked_cmds)
        return ToolResult.ok(
            {
                "total": len(lines),
                "shown": len(clients),
                "blocked_clients": blocked,
                "clients": clients,
            }
        )
    except Exception as e:
        return ToolResult.error(str(e))


async def redis_slowlog(plugin, params: dict[str, Any]) -> ToolResult:
    """SLOWLOG GET count"""
    try:
        count = max(1, min(int(params.get("count", 10)), 100))
        result = await plugin._run_redis_cli(f"SLOWLOG GET {count}", timeout=15)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "SLOWLOG GET failed")
        entries = [ln.strip() for ln in result["stdout"].splitlines() if ln.strip()]
        suggestions = []
        if entries:
            suggestions.append("Есть медленные команды — проверьте hot keys и O(N) операции")
        status = Status.HEALTHY if not entries else Status.DEGRADED
        return ToolResult(
            status=status,
            data={"count": len(entries), "entries": entries[:count]},
            suggestions=suggestions,
        )
    except Exception as e:
        return ToolResult.error(str(e))


async def redis_memory(plugin, params: dict[str, Any]) -> ToolResult:
    """Анализ памяти Redis по INFO memory"""
    try:
        result = await plugin._run_redis_cli("INFO memory", timeout=15)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "INFO memory failed")
        info = _parse_info(result["stdout"])
        used = int(info.get("used_memory", "0") or 0)
        peak = int(info.get("used_memory_peak", "0") or 0)
        frag = float(info.get("mem_fragmentation_ratio", "0") or 0)
        maxmem = int(info.get("maxmemory", "0") or 0)
        evicted = int(info.get("evicted_keys", "0") or 0)
        usage_pct = (used / maxmem * 100) if maxmem > 0 else 0.0
        issues: list[str] = []
        if maxmem > 0 and usage_pct > 90:
            issues.append(f"Memory usage {usage_pct:.1f}% of maxmemory — риск evictions/OOM")
        if evicted > 0:
            issues.append(f"evicted_keys={evicted} — возможны cache-miss каскады в DB")
        if frag > 1.5 or (0 < frag < 0.8):
            issues.append(f"mem_fragmentation_ratio={frag} — проверьте аллокатор")
        data = {
            "used_memory": used,
            "used_memory_human": info.get("used_memory_human", ""),
            "peak_memory": peak,
            "fragmentation_ratio": frag,
            "maxmemory": maxmem,
            "maxmemory_policy": info.get("maxmemory_policy", ""),
            "evicted_keys": evicted,
            "expired_keys": info.get("expired_keys", "0"),
            "usage_pct": round(usage_pct, 1),
        }
        if issues:
            return ToolResult.degraded(data, issues)
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))
