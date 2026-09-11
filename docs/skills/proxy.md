# Nginx — reverse proxy

Часть Skills (см. `docs/SKILLS.md`). Связки: `workflows.md`, корреляции — `correlations.md`.

## Nginx Diagnostics (5 tools)

| Tool | Description |
|------|-------------|
| `nginx_status` | Service status |
| `nginx_logs` | Error/access logs |
| `nginx_config` | Configuration check |
| `nginx_upstream` | Upstream servers: конфиг + реальный HTTP health check (возвращает `proxy_connect_timeout_s`, `connect_ms` для корреляции timeout==proxy_timeout) |
| `nginx_stub_status` | HTTP-проверка stub_status: active connections, requests, reading/writing/waiting |

Ключевое правило (INCIDENT_504): **таймаут ровно равный `proxy_connect_timeout` — подпись проблемы L3/L4 (SYN дропаются), а не медленного кода**. Сразу смотреть `linux_firewall` + `service_ip_filter` + `tcp_connect_as`.
