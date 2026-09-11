# Data — PostgreSQL + Redis

Часть Skills (см. `docs/SKILLS.md`). Связки: `workflows.md`, корреляции — `correlations.md`.

## PostgreSQL Diagnostics (7 tools)

| Tool | Description |
|------|-------------|
| `pg_connections` | Active connections |
| `pg_locks` | Lock information |
| `pg_slow_queries` | Slow query log |
| `pg_activity` | Full activity |
| `pg_stats` | Database statistics |
| `pg_replication` | Replication status |
| `pg_tables` | Table information |

Правило (INCIDENT_504): `DB_HOST` из конфига приложения сверять с `listen_addresses` PostgreSQL + `ss -tlnp` + `pg_hba.conf`. Не менять вслепую — postgres может слушать только внутренний адрес.

## Redis Cache (5 tools)

| Tool | Description |
|------|-------------|
| `redis_ping` | Availability check (PING) |
| `redis_info` | INFO sections: memory, clients, stats, replication |
| `redis_clients` | Client connections (CLIENT LIST) |
| `redis_slowlog` | Slow log (SLOWLOG GET) |
| `redis_memory` | Memory: used, peak, fragmentation, evictions |
