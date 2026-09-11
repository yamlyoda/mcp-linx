# Skills Index — симптом → файл

Карта навигации по `docs/skills/`. Часть Skills (см. `docs/SKILLS.md`).

| Симптом | Читать |
|---------|--------|
| Высокий CPU / память / диск, процессы, системные логи | `linux.md` |
| Сервис не стартует, failed unit, journal логи, подозрение на systemd IP-фильтр | `linux.md` (раздел Systemd) |
| 502/503/504 от Nginx, upstream недоступен, таймаут == proxy_connect_timeout | `proxy.md`, затем `netdiag.md` |
| Контейнер падает / рестартится / нет места | `containers.md` |
| Pod CrashLoop / OOMKilled / события кластера | `containers.md` (раздел Kubernetes) |
| Медленные запросы, блокировки, репликация, idle-in-transaction | `data.md` (раздел PostgreSQL) |
| Cache-miss, evictions, рост нагрузки на БД | `data.md` (раздел Redis) |
| Алерты, деградация по метрикам | `observability.md` (раздел Prometheus) |
| Поиск по логам за период инцидента | `observability.md` (раздел Loki) |
| Подключение refused/timeout, TLS expiry, DNS не резолвится, per-uid фильтры | `netdiag.md` |
| Нужна цепочка «что за чем вызывать» | `workflows.md` |
| Нужна таблица «что с чем коррелирует» | `correlations.md` |
| Пишу свой плагин / настраиваю config / подключаю MCP-клиент | `core.md` (идеология) + `custom.md` (как делать) |
