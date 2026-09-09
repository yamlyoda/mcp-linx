"""Tools kubernetes плагина (часть 1: pods, events, logs)"""

from __future__ import annotations

import json
import shlex
from typing import Any

from mcp_linx.types import Status, ToolResult

_BAD_PHASES = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "Error", "Failed", "Pending"}


def _ns(params: dict[str, Any], plugin) -> str:
    return str(params.get("namespace", "") or plugin._namespace)


async def k8s_pods(plugin, params: dict[str, Any]) -> ToolResult:
    """kubectl get pods -o json: фазы, рестарты, readiness"""
    try:
        ns = shlex.quote(_ns(params, plugin))
        base = plugin._kubectl_base()
        result = await plugin._run(f"{base} get pods -n {ns} -o json", timeout=20)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "kubectl get pods failed")
        items = json.loads(result["stdout"] or "{}").get("items", [])
        pods = []
        bad = 0
        for item in items:
            meta = item.get("metadata", {})
            st = item.get("status", {})
            css = st.get("containerStatuses", [])
            cs = css[0] if css else {}
            state = cs.get("state", {})
            waiting = (state.get("waiting") or {}).get("reason", "")
            phase = st.get("phase", "Unknown")
            restarts = cs.get("restartCount", 0)
            ready = cs.get("ready", False)
            is_bad = phase in ("Failed", "Pending") or waiting in _BAD_PHASES or (restarts or 0) > 5
            if is_bad:
                bad += 1
            pods.append({
                "name": meta.get("name", ""),
                "phase": phase,
                "waiting": waiting,
                "ready": ready,
                "restarts": restarts,
                "node": item.get("spec", {}).get("nodeName", ""),
            })
        data = {"total": len(pods), "problem": bad, "pods": pods}
        if bad:
            return ToolResult.degraded(data, [f"{bad} problem pods - see k8s_events/k8s_describe"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def k8s_events(plugin, params: dict[str, Any]) -> ToolResult:
    """kubectl get events: предупреждения кластера"""
    try:
        ns = shlex.quote(_ns(params, plugin))
        base = plugin._kubectl_base()
        result = await plugin._run(
            f"{base} get events -n {ns} --sort-by=.lastTimestamp -o json", timeout=20
        )
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "kubectl get events failed")
        items = json.loads(result["stdout"] or "{}").get("items", [])
        warns = [i for i in items if i.get("type") == "Warning"]
        events = []
        for i in items[-50:]:
            obj = i.get("involvedObject", {})
            events.append({
                "reason": i.get("reason", ""),
                "message": (i.get("message", "") or "")[:300],
                "object": f"{obj.get('kind', '')}/{obj.get('name', '')}",
                "count": i.get("count", 1),
            })
        data = {"total": len(items), "warnings": len(warns), "events": events}
        if warns:
            return ToolResult.degraded(data, [f"{len(warns)} Warning events"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def k8s_logs(plugin, params: dict[str, Any]) -> ToolResult:
    """kubectl logs pod: логи контейнера"""
    try:
        pod = str(params.get("pod", "")).strip()
        if not pod or not all(c.isalnum() or c in "-." for c in pod):
            return ToolResult.error("Param 'pod' is required (alphanum, dash, dot)")
        ns = shlex.quote(_ns(params, plugin))
        lines = max(10, min(int(params.get("lines", 100)), 500))
        container = str(params.get("container", "")).strip()
        prev = bool(params.get("previous", False))
        base = plugin._kubectl_base()
        cmd = f"{base} logs {shlex.quote(pod)} -n {ns} --tail={lines}"
        if container:
            cmd += f" -c {shlex.quote(container)}"
        if prev:
            cmd += " -p"
        result = await plugin._run(cmd, timeout=20)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "kubectl logs failed")
        return ToolResult.ok({"pod": pod, "logs": result["stdout"]})
    except Exception as e:
        return ToolResult.error(str(e))


async def k8s_describe(plugin, params: dict[str, Any]) -> ToolResult:
    """kubectl get pod -o json: conditions пода"""
    try:
        pod = str(params.get("pod", "")).strip()
        if not pod or not all(c.isalnum() or c in "-." for c in pod):
            return ToolResult.error("Param 'pod' is required (alphanum, dash, dot)")
        ns = shlex.quote(_ns(params, plugin))
        base = plugin._kubectl_base()
        result = await plugin._run(f"{base} get pod {shlex.quote(pod)} -n {ns} -o json", timeout=20)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "kubectl get pod failed")
        pod_obj = json.loads(result["stdout"] or "{}")
        st = pod_obj.get("status", {})
        conditions = [
            {k: c.get(k) for k in ("type", "status", "reason", "message")}
            for c in st.get("conditions", [])
        ]
        data = {
            "pod": pod,
            "phase": st.get("phase", ""),
            "conditions": conditions,
            "container_statuses": st.get("containerStatuses", []),
        }
        not_ready = [c for c in conditions if c.get("type") == "Ready" and c.get("status") == "False"]
        if not_ready:
            return ToolResult.degraded(data, [f"Pod {pod} not Ready"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))


async def k8s_top(plugin, params: dict[str, Any]) -> ToolResult:
    """kubectl top pods: ресурсы подов"""
    try:
        ns = shlex.quote(_ns(params, plugin))
        base = plugin._kubectl_base()
        result = await plugin._run(f"{base} top pods -n {ns} --no-headers", timeout=20)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "kubectl top failed (metrics-server?)")
        rows = [ln.split() for ln in result["stdout"].splitlines() if ln.strip()]
        pods = [
            {"pod": r[0], "cpu": r[1] if len(r) > 1 else "", "memory": r[2] if len(r) > 2 else ""}
            for r in rows
        ]
        return ToolResult.ok({"pods": pods})
    except Exception as e:
        return ToolResult.error(str(e))


async def k8s_deployments(plugin, params: dict[str, Any]) -> ToolResult:
    """kubectl get deployments: available vs desired"""
    try:
        ns = shlex.quote(_ns(params, plugin))
        base = plugin._kubectl_base()
        result = await plugin._run(f"{base} get deployments -n {ns} -o json", timeout=20)
        if result["returncode"] != 0:
            return ToolResult.error(result["stderr"][:500] or "kubectl get deployments failed")
        items = json.loads(result["stdout"] or "{}").get("items", [])
        deps = []
        bad = 0
        for item in items:
            st = item.get("status", {})
            desired = st.get("replicas", 0)
            avail = st.get("availableReplicas", 0)
            if avail < desired:
                bad += 1
            deps.append({
                "name": item.get("metadata", {}).get("name", ""),
                "desired": desired,
                "available": avail,
                "updated": st.get("updatedReplicas", 0),
            })
        data = {"total": len(deps), "degraded": bad, "deployments": deps}
        if bad:
            return ToolResult.degraded(data, [f"{bad} deployments not fully available"])
        return ToolResult.ok(data)
    except Exception as e:
        return ToolResult.error(str(e))

        return ToolResult.error(str(e))
