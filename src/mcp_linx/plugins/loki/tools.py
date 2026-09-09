"""Tools loki плагина: search, labels, tail"""

from __future__ import annotations

from typing import Any

import httpx

from mcp_linx.types import ToolResult


def _check_logql(query: str) -> str | None:
    q = query.strip()
    if not q:
        return "Param 'query' is required (LogQL, e.g. {app=\"nginx\"} |= \"error\")"
    if len(q) > 2000:
        return "Query too long (max 2000 chars)"
    return None


async def log_search(plugin, params: dict[str, Any]) -> ToolResult:
    """GET /loki/api/v1/query_range: поиск за период"""
    query = str(params.get("query", ""))
    err = _check_logql(query)
    if err:
        return ToolResult.error(err)
    try:
        limit = max(10, min(int(params.get("limit", 100)), 1000))
        start = str(params.get("start", "-1h"))
        end = str(params.get("end", "now"))
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/loki/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "limit": limit},
                headers=plugin._headers(),
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Loki HTTP {resp.status_code}: {resp.text[:300]}")
        streams = resp.json().get("data", {}).get("result", [])
        total = sum(len(s.get("values", [])) for s in streams)
        entries = []
        for s in streams[:10]:
            for ts, line in s.get("values", [])[-20:]:
                entries.append({"stream": s.get("stream", {}), "line": line[:500]})
        return ToolResult.ok({
            "query": query, "streams": len(streams),
            "total_lines": total, "entries": entries[:limit],
        })
    except Exception as e:
        return ToolResult.error(str(e))


async def log_labels(plugin, params: dict[str, Any]) -> ToolResult:
    """GET /loki/api/v1/labels + values: какие сервисы пишут логи"""
    try:
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/loki/api/v1/labels", headers=plugin._headers()
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Loki HTTP {resp.status_code}: {resp.text[:300]}")
        labels = resp.json().get("data", [])
        values: dict[str, list[str]] = {}
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            for label in labels[:10]:
                r = await client.get(
                    f"{plugin._base_url}/loki/api/v1/label/{label}/values",
                    headers=plugin._headers(),
                )
                if r.status_code == 200:
                    values[label] = r.json().get("data", [])[:30]
        return ToolResult.ok({"labels": labels, "values": values})
    except Exception as e:
        return ToolResult.error(str(e))


async def log_tail(plugin, params: dict[str, Any]) -> ToolResult:
    """Последние строки по селектору"""
    query = str(params.get("query", ""))
    err = _check_logql(query)
    if err:
        return ToolResult.error(err)
    try:
        limit = max(10, min(int(params.get("limit", 50)), 500))
        async with httpx.AsyncClient(timeout=plugin._timeout) as client:
            resp = await client.get(
                f"{plugin._base_url}/loki/api/v1/query_range",
                params={"query": query, "start": "-15m", "end": "now", "limit": limit},
                headers=plugin._headers(),
            )
        if resp.status_code != 200:
            return ToolResult.error(f"Loki HTTP {resp.status_code}: {resp.text[:300]}")
        streams = resp.json().get("data", {}).get("result", [])
        lines = []
        for s in streams:
            for _, line in s.get("values", [])[-limit:]:
                lines.append(line[:500])
        return ToolResult.ok({"query": query, "lines": lines[-limit:]})
    except Exception as e:
        return ToolResult.error(str(e))
