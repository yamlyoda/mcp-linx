# Netdiag — сеть, TLS, DNS, TCP

Часть Skills (см. `docs/SKILLS.md`). Связки: `workflows.md`, корреляции — `correlations.md`.

## Netdiag (6 tools)

| Tool | Description |
|------|-------------|
| `http_check` | HTTP(S) check: status, timings, redirects |
| `tls_check` | TLS certificate: expiry, chain, issuer |
| `dns_resolve` | DNS resolution A/AAAA |
| `tcp_connect` | TCP connect with timing |
| `tcp_connect_as` | TCP-проба от имени сервисного пользователя — находит per-uid фильтры (nft skuid). Требует `privileged_tools: true` |
| `tcpdump_probe` | Короткий tcpdump-срез host:port. 0 пакетов при активном connect() = дроп ниже интерфейса. Требует `privileged_tools: true` |

## Privileged-флаг

```yaml
plugins:
  netdiag:
    privileged_tools: false  # tcp_connect_as / tcpdump_probe (runuser, tcpdump) — только чтение с лимитами
```

По умолчанию `false`: tools возвращают `error` с готовой ручной командой. Кейс из INCIDENT_504: `tcp_connect` как root — OK, `tcp_connect_as` как `www-data` — FAIL → per-uid фильтр.
