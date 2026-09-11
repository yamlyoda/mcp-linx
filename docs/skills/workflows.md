# Workflows — цепочки диагностики

Часть Skills (см. `docs/SKILLS.md`). Таблицы tools — в файлах `linux.md`, `proxy.md`, `containers.md`, `data.md`, `observability.md`, `netdiag.md`.

## Common Workflows

### Performance Issue
```
linux_host_stats → linux_processes → linux_memory
```

### Website Slow
```
nginx_logs(error) → docker_stats → pg_slow_queries
```

### Container Down
```
docker_containers → docker_logs → docker_events
```

### Database Issues
```
pg_slow_queries → pg_activity → pg_locks
```

### Cache Issues
```
redis_memory → redis_slowlog → redis_clients → pg_slow_queries
```

### Website Down
```
http_check → tls_check → nginx_logs → docker_containers
```

### K8s Pod CrashLoop
```
k8s_pods → k8s_events → k8s_logs → k8s_describe
```

### Alerts Firing
```
prom_alerts → prom_targets → prom_query → linux_host_stats
```

### Log Investigation
```
log_labels → log_search → log_tail → docker_logs
```

### 504 Gateway Timeout (INCIDENT_504)
```
nginx_upstream (proxy_connect_timeout_s, connect_ms) → tcp_connect_as (www-data) → linux_firewall (marks/blackhole) → service_ip_filter (eBPF whitelist) → tcpdump_probe (0 пакетов = дроп ниже интерфейса)
```
