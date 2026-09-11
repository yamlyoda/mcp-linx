"""Tools systemd плагина"""

from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any

from mcp_linx.types import Status, ToolResult

_UNIT_RE = re.compile(r"^[A-Za-z0-9@:_.\-]+\.(service|socket|timer|target|mount|device)$")


def _check_unit(unit: str) -> str | None:
    if not _UNIT_RE.match(unit):
        return f"Invalid unit name '{unit}'. Expected e.g. nginx.service"
    return None


def _decode_lpm_cidr(prefix_len: int, addr_bytes: bytes) -> str:
    """Декодировать LPM-trie ключ (prefix_len + raw bytes) в CIDR-строку."""
    try:
        if len(addr_bytes) == 4:
            ip = ipaddress.IPv4Address(addr_bytes)
        elif len(addr_bytes) == 16:
            ip = ipaddress.IPv6Address(addr_bytes)
        else:
            return f"<{len(addr_bytes)}b hex={addr_bytes.hex()}>/{prefix_len}"
        net = ipaddress.ip_network(f"{ip}/{prefix_len}", strict=False)
        return str(net)
    except Exception:
        return f"<hex={addr_bytes.hex()}>/{prefix_len}"


def _parse_bpftool_map_dump(text: str) -> list[str]:
    """Распарсить `bpftool map dump` LPM-trie в список CIDR.

    Формат строк:
        key: 08 00 00 00 7f 00 00 00  value: ...
    Первые 4 байта LE = prefix_len, остальное = адрес.
    """
    cidrs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("key:"):
            continue
        # key: XX XX ...  value: ...
        key_part = line[len("key:") :].split("value:")[0].strip()
        hexbytes = bytes(int(x, 16) for x in key_part.split() if len(x) == 2)
        if len(hexbytes) < 4:
            continue
        prefix_len = int.from_bytes(hexbytes[:4], "little")
        addr = bytes(hexbytes[4:])
        cidrs.append(_decode_lpm_cidr(prefix_len, addr))
    return cidrs


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
            return ToolResult.degraded(
                data, [f"{len(units)} failed units — проверьте service_logs"]
            )
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
        errors = sum(
            1 for ln in text.splitlines() if "error" in ln.lower() or "failed" in ln.lower()
        )
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
        return ToolResult.ok(
            {
                "summary": total["stdout"].strip(),
                "slowest": lines,
            }
        )
    except Exception as e:
        return ToolResult.error(str(e))


async def service_ip_filter(plugin, params: dict[str, Any]) -> ToolResult:
    """Эффективный IP-фильтр юнита: unit-файлы + bpftool (ground truth).

    `systemctl show` может скрывать фильтр, навязанный внешней системой
    (см. INCIDENT_504): eBPF map — ground truth, unit-файлы — нет.
    Read-only: только systemctl show / bpftool show / dump.
    """
    unit = str(params.get("unit", "")).strip()
    err = _check_unit(unit)
    if err:
        return ToolResult.error(err)
    try:
        q = shlex.quote(unit)
        data: dict[str, Any] = {"unit": unit}

        # 1. Что декларируют unit-файлы
        show = await plugin._run(
            f"systemctl show {q} -p IPAddressAllow -p IPAddressDeny "
            f"-p IPAccounting -p IPAddressAllowExtra 2>/dev/null",
            timeout=10,
        )
        declared: dict[str, str] = {}
        for ln in show["stdout"].splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                declared[k.strip()] = v.strip()
        data["declared"] = declared

        # 2. eBPF программы cgroup_skb на cgroup юнита
        cgroup = await plugin._run(
            f"bpftool cgroup show /sys/fs/cgroup/system.slice/{q} 2>&1 || "
            f"bpftool cgroup show /sys/fs/cgroup/{q} 2>&1 || echo 'NO_CGROUP_BPF'",
            timeout=10,
        )
        data["cgroup_bpf_raw"] = cgroup["stdout"][:2000]

        # 3. Все cgroup_skb программы + их maps
        progs = await plugin._run("bpftool prog show 2>&1 | head -60", timeout=10)
        prog_text = progs["stdout"]
        data["progs_raw"] = prog_text[:3000]
        unit_progs = [
            ln.strip()
            for ln in prog_text.splitlines()
            if "cgroup_skb" in ln and (unit.replace(".service", "") in ln or "sd_fw" in ln)
        ]
        data["unit_progs"] = unit_progs

        # 4. LPM-whitelist maps для юнита: bpftool map list → dump
        maps = await plugin._run("bpftool map list 2>&1 | head -60", timeout=10)
        map_text = maps["stdout"]
        data["maps_raw"] = map_text[:2000]
        short = unit.replace(".service", "")
        effective_allow: list[str] = []
        dumped: list[dict[str, Any]] = []
        # Dump по именам map, связанных с юнитом
        for m in re.finditer(r"name\s+(\S*" + re.escape(short) + r"\S*|\S*sd_fw\S*)", map_text):
            map_name = m.group(1)
            dump = await plugin._run(
                f"bpftool map dump name {shlex.quote(map_name)} 2>&1", timeout=10
            )
            cidrs = _parse_bpftool_map_dump(dump["stdout"])
            dumped.append({"map": map_name, "cidrs": cidrs, "raw": dump["stdout"][:2000]})
            effective_allow.extend(cidrs)
        data["effective_allow"] = sorted(set(effective_allow))
        data["dumped_maps"] = dumped

        # 5. Вердикт
        hidden = bool(effective_allow) and not declared.get("IPAddressAllow")
        issues: list[str] = []
        if hidden:
            issues.append(
                f"Скрытый IP-фильтр: eBPF whitelist={data['effective_allow']}, "
                f"но IPAddressAllow в unit-файлах пуст — фильтр навязан внешней системой "
                f"(см. docs/INCIDENT_504.md). Проверьте drop-in /etc/systemd/system/{unit}.d/"
            )
        if not effective_allow and not declared.get("IPAddressAllow"):
            return ToolResult.ok({**data, "verdict": "no_ip_filter_detected"})
        if issues:
            return ToolResult.degraded(
                {**data, "verdict": "hidden_filter" if hidden else "filtered"}, issues
            )
        return ToolResult.ok({**data, "verdict": "filtered"})
    except Exception as e:
        return ToolResult.error(str(e))
