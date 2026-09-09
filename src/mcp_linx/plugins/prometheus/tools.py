"""Tools prometheus плагина"""

from __future__ import annotations

from typing import Any

import httpx

from mcp_linx.types import Status, ToolResult


def _check_promql(query: str) -> str | None:
    q = query.strip()
    if not q:
        return "Param 'query' is required"
    if len(q) > 2000:
        return "Query too long (max 2000 chars)"
    return None


async def prom_query(plugin, params: dict[str, Any]) -> ToolResult:
    """GET /api/v1/query?query=<PromQL>"""
    query = str(params.get("query", ""))
    err = _check_promql(query)
    if err:
        return ToolResult.error(err)
    try:
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/api/v1/query",
                params={"query": query},
                headers=plugin._headers(),
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Prometheus HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("status") != "success":
            return ToolResult.error(f"Prometheus error: {str(body)[:500]}")
        result = body.get("data", {}).get("result", [])
        return ToolResult.ok({"query": query, "count": len(result), "result": result[:100]})
    except Exception as e:
        return ToolResult.error(str(e))


async def prom_range(plugin, params: dict[str, Any]) -> ToolResult:
    """GET /api/v1/query_range: история метрики"""
    query = str(params.get("query", ""))
    err = _check_promql(query)
    if err:
        return ToolResult.error(err)
    try:
        start = str(params.get("start", "-1h"))
        end = str(params.get("end", "now"))
        step = str(params.get("step", "1m"))
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
                headers=plugin._headers(),
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Prometheus HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("status") != "success":
            return ToolResult.error(f"Prometheus error: {str(body)[:500]}")
        result = body.get("data", {}).get("result", [])
        return ToolResult.ok({"query": query, "series": len(result), "result": result[:20]})
    except Exception as e:
        return ToolResult.error(str(e))


async def prom_alerts(plugin, params: dict[str, Any]) -> ToolResult:
    """GET /api/v1/alerts: firing/pending алерты"""
    try:
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/api/v1/alerts", headers=plugin._headers()
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Prometheus HTTP {resp.status_code}: {resp.text[:300]}")
        alerts = resp.json().get("data", {}).get("alerts", [])
        firing = [a for a in alerts if a.get("state") == "firing"]
        data = {"total": len(alerts), "firing": len(firing), "alerts": alerts[:50]}
        if firing:
            names = sorted({a.get("labels", {}).get("alertname", "?") for a in firing})
            return ToolResult.degraded(data, [f"Firing: {', '.join(names[:10])}"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def prom_targets(plugin, params: dict[str, Any]) -> ToolResult:
    """GET /api/v1/targets: up/down scrape targets"""
    try:
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/api/v1/targets", headers=plugin._headers()
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Prometheus HTTP {resp.status_code}: {resp.text[:300]}")
        targets = resp.json().get("data", {}).get("activeTargets", [])
        down = [t for t in targets if t.get("health") != "up"]
        data = {
            "total": len(targets),
            "down": len(down),
            "down_targets": [
                {"job": t.get("labels", {}).get("job", ""),
                 "instance": t.get("labels", {}).get("instance", ""),
                 "last_error": (t.get("lastError", "") or "")[:200]}
                for t in down[:20]
            ],
        }
        if down:
            return ToolResult.degraded(data, [f"{len(down)} targets down"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))
