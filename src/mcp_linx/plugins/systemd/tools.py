"""Tools systemd плагина"""

from __future__ import annotations

import re
import shlex
from typing import Any

from mcp_linx.types import Status, ToolResult

_UNIT_RE = re.compile(r"^[A-Za-z0-9@:_.\-]+\.(service|socket|timer|target|mount|device)$")


def _check_unit(unit: str) -> str | None:
    if not _UNIT_RE.match(unit):
        return f"Invalid unit name '{unit}'. Expected e.g. nginx.service"
    return None


async def service_status(plugin, params: dict[str, Any]) -> ToolResult:
    """systemctl status/is-active/is-enabled для юнита"""
    unit = str(params.get("unit", "")).strip()
    err = _check_unit(unit)
    if err:
        return ToolResult.error(err)
    try:
        q = shlex.quote(unit)
        active = await plugin._run(f"systemctl is-active {q}", timeout=10)
        enabled = await plugin._run(f"systemctl is-enabled {q}", timeout=10)
        status = await plugin._run(f"systemctl status {q} --no-pager -l", timeout=15)
        state = active["stdout"].strip() or "unknown"
        data = {
            "unit": unit,
            "active_state": state,
            "enabled": enabled["stdout"].strip(),
            "status_output": status["stdout"][:4000],
        }
        if state == "active":
            return ToolResult.ok(data)
        if state in ("failed", "inactive"):
            return ToolResult.degraded(data, [f"Unit {unit} is {state} — см. service_logs"])
        return ToolResult(status=Status.UNKNOWN, data=data)
    except Exception as e:
        return ToolResult.error(str(e))


async def failed_units(plugin, params: dict[str, Any]) -> ToolResult:
    """systemctl --failed — список упавших юнитов"""
    try:
        result = await plugin._run("systemctl --failed --no-pager --no-legend", timeout=15)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "systemctl --failed failed")
        units = [ln.strip() for ln in result["stdout"].splitlines() if ln.strip()]
        data = {"count": len(units), "units": units}
        if units:
            return ToolResult.degraded(data, [f"{len(units)} failed units — проверьте service_logs"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def service_logs(plugin, params: dict[str, Any]) -> ToolResult:
    """journalctl -u <unit> — логи сервиса"""
    unit = str(params.get("unit", "")).strip()
    err = _check_unit(unit)
    if err:
        return ToolResult.error(err)
    try:
        lines = max(10, min(int(params.get("lines", 100)), 500))
        priority = str(params.get("priority", "")).strip()
        q = shlex.quote(unit)
        cmd = f"journalctl -u {q} -n {lines} --no-pager"
        if priority:
            cmd += f" -p {shlex.quote(priority)}"
        result = await plugin._run(cmd, timeout=20)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "journalctl failed")
        text = result["stdout"]
        errors = sum(1 for ln in text.splitlines() if "error" in ln.lower() or "failed" in ln.lower())
        return ToolResult.ok({"unit": unit, "lines": lines, "error_hits": errors, "logs": text})
    except Exception as e:
        return ToolResult.error(str(e))


async def boot_analysis(plugin, params: dict[str, Any]) -> ToolResult:
    """systemd-analyze blame — кто тормозит загрузку"""
    try:
        top = max(5, min(int(params.get("top", 15)), 50))
        blame = await plugin._run("systemd-analyze blame --no-pager", timeout=20)
        total = await plugin._run("systemd-analyze", timeout=15)
        if blame["returncode"] != 0:
            return ToolResult.error(blame["stderr"][:500] or "systemd-analyze failed")
        lines = [ln.strip() for ln in blame["stdout"].splitlines() if ln.strip()][:top]
        return ToolResult.ok({
            "summary": total["stdout"].strip(),
            "slowest": lines,
        })
    except Exception as e:
        return ToolResult.error(str(e))
