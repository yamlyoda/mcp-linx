# Skills Documentation

Skills in MCP-Linx follow the **Harness ideology**: skills are plugins that can be loaded, combined, and swapped via configuration. Details split by topic in `docs/skills/` - load only what the incident needs.

## Index

| Topic | File | Contents |
|-------|------|----------|
| Navigation | `skills/_index.md` | symptom to file map |
| Ideology | `skills/core.md` | Harness, What is a Skill, Best Practices |
| Host | `skills/linux.md` | Linux (8 tools) + Systemd (5 tools) |
| Proxy | `skills/proxy.md` | Nginx (5 tools) |
| Runtimes | `skills/containers.md` | Docker (7) + Kubernetes (6) |
| Data | `skills/data.md` | PostgreSQL (7) + Redis (5) |
| Observability | `skills/observability.md` | Prometheus (4) + Loki (3) |
| Network | `skills/netdiag.md` | Netdiag (6 tools, incl. privileged) |
| Chains | `skills/workflows.md` | 10 workflows (incl. 504 Gateway Timeout) |
| Correlations | `skills/correlations.md` | 9 rules (incl. 3x INCIDENT_504) |
| Custom | `skills/custom.md` | Create plugin, Configuration, MCP Client Setup |

## System Tools (always loaded)

| Tool | Description |
|------|-------------|
| `get_diagnostic_context` | Full diagnostic context with correlations |
| `get_summary` | Status summary |
| `system_health_check` | Health check all plugins |

Total: 10 plugins / 56 tools + 3 system tools.
