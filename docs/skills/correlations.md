# Correlations — что с чем коррелирует

Часть Skills (см. `docs/SKILLS.md`). Реализация — `src/mcp_linx/context_aggregator.py`.

## Correlation Engine

| Correlation | Trigger |
|-------------|---------|
| Docker + Nginx | Docker down, Nginx critical |
| Linux + Docker | Linux critical, Docker degraded |
| PG + Docker | PG degraded, Docker healthy |
| Redis + PG | Redis evictions, PG degraded (cache-miss cascade) |
| Linux + K8s | K8s CrashLoop/OOMKilled, host memory pressure |
| Netdiag + Nginx | TLS cert issue, Nginx failing |
| Nginx timeout == proxy_connect_timeout | Upstream timeout совпадает с proxy_connect_timeout → SYN дропается (firewall/nft/eBPF), а не медленный upstream (INCIDENT_504) |
| Netdiag per-uid fail | TCP-проба проходит от одного uid, падает от сервисного → per-uid фильтр, смотреть linux_firewall + service_ip_filter (INCIDENT_504) |
| Postgres DB_HOST mismatch | DB_HOST из конфига не совпадает с listen_addresses → сверить ss -tlnp + pg_hba.conf (INCIDENT_504) |
