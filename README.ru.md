# MCP-Linx — MCP-сервер диагностики Linux-инфраструктуры

> English version: [`README.md`](./README.md).

> **Статус: Alpha (1.0.0).** API плагинов/инструментов и ключи конфигурации могут
> меняться без периода устаревания. Не рассчитан на недоверенные сети — см.
> [Безопасность](#security--безопасность).

MCP-Linx — это MCP (Model Context Protocol) сервер для диагностики Linux-инфраструктуры. Он предоставляет инструменты для мониторинга и диагностики компонентов: Linux host, Nginx, Docker, PostgreSQL, Redis, Systemd, Netdiag, Kubernetes, Prometheus, Loki.

---

## Установка

```bash
# Создание виртуального окружения
python3.11 -m venv .venv
source .venv/bin/activate

# Установка зависимостей
pip install -e ".[dev]"
```

---

## Running the Server / Запуск сервера

```bash
# Запуск MCP сервера (stdio режим)
python -m mcp_linx.main

# С запуском MCP Inspector для отладки
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

### Docker


Один образ — две модели запуска:

- **Модель A (по умолчанию, безопасная)** — изолированный контейнер диагностирует *удалённые* хосты по SSH; postgres/redis/prometheus/loki/k8s — по сети.
- **Модель B (host)** — диагностика *самого* хоста (только Linux): нужны `pid: host`, `network_mode: host` и read-only маунты (см. `docker-compose.yml`). Внимание: маунт `docker.sock` даёт root-доступ к хосту Docker.

```bash
# Сборка
docker build -t mcp-linx:latest .

# Запуск через compose (stdio; MCP-клиенты: command=docker, args=["run","-i","--rm","mcp-linx:latest"])
docker compose run --rm mcp-linx
```

---

## Configuration / Конфигурация

Основной конфигурационный файл: `config/settings.yaml`

**Русский:** Основной конфигурационный файл: `config/settings.yaml`

Переменные окружения: скопируйте `.env.example` → `.env` только для пяти настроек
сервера (имена без префикса). Секреты плагинов передавайте через **окружение процесса**,
не через `.env`: неизвестные ключи в dotenv вызывают ошибку валидации.
`${VAR}` / `${VAR:-default}` в YAML читают окружение процесса. Если переменная
отсутствует и default не задан, сервер пишет warning и использует весь исходный YAML
без подстановки. Пустое значение переменной не включает default. Подстановка текстовая,
до разбора YAML: значение должно быть допустимо в используемом YAML-кавычении.
Настройка локального запуска и Docker, аудит и завершение описаны в
[руководстве разработчика](docs/DEVELOPMENT.md#environment-and-configuration).

`plugins.enabled` задаёт активный набор плагинов: только перечисленные загружаются,
инициализируются, регистрируют MCP-инструменты и участвуют в health-check. Пустой
или отсутствующий список = все обнаруженные плагины. Это конфигурация состава,
а не граница доступа (системные инструменты и транспорт MCP не затрагиваются).

```yaml
security:
  readonly: true                    # Проверка команд; не запрет записи через Docker API
  max_command_output_size: 10000
  max_log_lines: 500
  command_timeout_seconds: 30      # Дефолтный таймаут команд плагинов (per-tool перекрывает)
  rate_limit_max_calls: 60         # Вызовов на инструмент за скользящее окно
  rate_limit_window_seconds: 60    # Размер окна в секундах
  allowed_hosts: [localhost]      # Добавьте имена из hosts: для удалённых вызовов

# Multi-host: named remote targets for SSH-based diagnostics.
# Мультихост: именованные удалённые хосты для диагностики по SSH.
# Tools accepting registry `host`: linux_*, nginx_* (кроме nginx_stub_status), systemd_*.
hosts: {}
# hosts:
#   web-1:
#     host: 10.130.0.23
#     port: 22
#     username: user
#     key_file: ~/.ssh/id_rsa
#     password: null                 # prefer env / key auth, не хранить в файле
#     host_key_policy: reject        # reject | warning | auto_add
#     known_hosts: null

plugins:
  enabled:
    - linux
    - nginx
    - docker
    - postgres
    - redis
    - systemd
    - netdiag
    - kubernetes
    - prometheus
    - loki

  postgres:
    host: "localhost"
    port: 5432
    password: "${POSTGRES_PASSWORD:-}" # Из окружения процесса; пусто, если не задано
    # SSL/TLS modes: disable | allow | prefer | require | verify-ca | verify-full
    # verify-full is recommended for production (verifies CA + hostname)
    ssl_mode: "prefer"

  redis:
    host: "localhost"
    port: 6379
    password: "${REDIS_PASSWORD:-}" # Из окружения процесса; пусто, если не задано

  nginx:
    log_path: "/var/log/nginx"
    stub_status_url: null # e.g. "http://127.0.0.1/nginx_status" — enables nginx_stub_status tool

  kubernetes:
    namespace: "default"
```

---

### SSL-режимы PostgreSQL

`plugins.postgres.ssl_mode` передаётся в libpq как `sslmode` (через `psycopg2.connect`),
поэтому значения и семантика — libpq:

| Режим | Шифрование | Сертификат сервера | Проверка имени хоста |
|---|---|---|---|
| `disable` | нет | — | — |
| `allow` | если требует сервер | нет | нет |
| `prefer` (по умолчанию) | да, если доступно | нет | нет |
| `require` | да | нет | нет |
| `verify-ca` | да | да (CA должен быть доверенным) | нет |
| `verify-full` | да | да | да |

`prefer` защищает только от пассивного прослушивания: при отсутствии TLS соединение
молча уходит в открытый текст. Для продакшена используйте `verify-full` (минимум
`verify-ca`), обеспечьте доступность CA процессу (`~/.postgresql/root.crt` или
системное хранилище) и держите `host` равным имени в сертификате — иначе соединение
упадёт, а не понизится в защите. Отдельного ключа для пути к CA у сервера нет:
используйте стандартные места libpq или `PGSSLROOTCERT` в окружении процесса.

---

### Надёжность SSH: повторы и туннели

Выполнение SSH-команд повторяется при ошибках **уровня соединения**, с переподключением (E1):

| Ключ | Где | По умолчанию | Смысл |
|---|---|---|---|
| `retry_attempts` | `hosts.<имя>` / `plugins.<плагин>.ssh` | `2` | всего попыток; `1` отключает повторы |
| `retry_backoff_seconds` | там же | `0.5` | базовая пауза, растёт линейно (× номер попытки) |

Повторяются только ошибки соединения (`SSHException`, `EOFError`, `OSError`,
`ConnectionError`). Ненулевой код возврата команды — обычный результат и не
ретраится: read-only диагностика остаётся предсказуемой.

PostgreSQL можно достать через SSH-сервер (E2) — например, если БД доступна только
с bastion-хоста:

```yaml
plugins:
  postgres:
    host: db.internal      # резолвится на стороне SSH
    port: 5432
    ssh:
      host: bastion        # SSH-сервер для туннеля
      username: ops
      key_file: ~/.ssh/id_rsa
      tunnel: true         # включается явно; требует ssh.host
```

Плагин открывает локальный `127.0.0.1:<порт>` и форвардит его на `db.internal:5432`
через SSH-соединение; туннель закрывается при `destroy()`. Redis в этом не нуждается:
его инструменты выполняют `redis-cli` на удалённом хосте по SSH. Учтите, что при
туннеле проверка имени хоста (`verify-full`) применяется к адресу туннеля, поэтому
предпочтительнее `verify-ca` с доверенным CA.

Сквозная проверка туннеля требует реального SSH-сервера и в CI не покрыта
(юнит-тесты используют фейковый транспорт и проверяют форвардинг и wiring).

### Jump host (бастион)

Именованный хост можно достать через бастион: пул открывает `direct-tcpip` канал
на бастионе и ведёт SSH-сессию до цели через него (E3):

```yaml
hosts:
  db-1:
    host: 10.0.0.20          # цель, резолвится на бастионе
    username: ops
    key_file: ~/.ssh/id_rsa
    jump_host: bastion.example.com
    jump_port: 22            # по умолчанию 22
    jump_username: jumper
    jump_key_file: ~/.ssh/jump
    # jump_password: передавайте через env-подстановку, не литералом
    host_key_policy: reject  # применяется и к бастиону, и к цели
```

Бастион проверяется той же политикой `host_key_policy` / `known_hosts`, что и цель
(при `reject` нужны ключи обоих в `known_hosts`). Соединение к бастиону
переиспользуется вместе с целевым и закрывается вместе с ним (`drop` / `close_all`).

### Несколько таргетов PostgreSQL

Любой инструмент `pg_*` принимает `host: <имя таргета>`, где таргеты описаны в конфиге
(E4b). Каждый таргет получает собственное соединение, а при `ssh.tunnel: true` — и
собственный туннель: primary и реплику за bastion можно диагностировать из одного
инстанса:

```yaml
plugins:
  postgres:
    host: primary.db           # используется, если инструмент вызван без `host`
    port: 5432
    user: postgres
    password: "${POSTGRES_PASSWORD:-}"
    targets:
      replica:
        host: replica.db
      behind-bastion:          # доступен по SSH (E2)
        host: internal.db
        ssh: {host: bastion, tunnel: true}
```

Неуказанные поля наследуются от настроек плагина. Неизвестное имя таргета даёт ошибку
со списком настроенных. Соединения и туннели закрываются в `destroy()`.

### Несколько кластеров Kubernetes

Плагин Kubernetes работает с одним кластером на инстанс, выбираемым через
`plugins.kubernetes.kubeconfig` / `context`. Для нескольких кластеров запускайте
дополнительные инстансы (отдельный `CONFIG_PATH`) или переключайте `context` —
у инструментов `k8s_*` намеренно нет аргумента выбора кластера.

---

## Tools / Инструменты

### Linux Plugin (8 tools)
- `linux_host_stats` — Host statistics: CPU, memory, disk, load
- `linux_processes` — List of running processes
- `linux_logs` — Read system logs (journalctl, syslog)
- `linux_network` — Network interfaces, ports, connections
- `linux_firewall` — Firewall snapshot: nftables + policy routing (read-only)
- `linux_disk` — Disk and filesystem usage
- `linux_memory` — Detailed memory usage information
- `linux_execute_command` — Execute an arbitrary read-only command

### Nginx Plugin (5 tools)
- `nginx_status` — Nginx service status and processes
- `nginx_logs` — Read error and access logs
- `nginx_config` — Nginx configuration check
- `nginx_upstream` — Upstream servers: config + real HTTP health check
- `nginx_stub_status` — stub_status metrics: active connections, requests

### Docker Plugin (7 tools)
- `docker_containers` — List containers with filtering
- `docker_logs` — Container logs
- `docker_stats` — Container stats: CPU, memory, network
- `docker_info` — Full container or system info
- `docker_events` — Docker events
- `docker_system_df` — Docker disk usage
- `docker_prune` — Dry-run по умолчанию; удаление требует `execute=true` и `confirm=true`

### PostgreSQL Plugin (7 tools)
- `pg_connections` — Active connections
- `pg_locks` — Locks and blocked queries
- `pg_slow_queries` — Slow queries
- `pg_activity` — Full activity: current queries, states, waits
- `pg_stats` — Statistics: tables, indexes, databases
- `pg_replication` — Replication status (if configured)
- `pg_tables` — List of tables with sizes and stats

### Redis Plugin (5 tools)
- `redis_ping` — Redis availability (PING)
- `redis_info` — INFO sections: memory, clients, stats, replication
- `redis_clients` — Client connections (CLIENT LIST)
- `redis_slowlog` — Slow log (SLOWLOG GET)
- `redis_memory` — Memory analysis: used, peak, fragmentation, evictions

### Systemd Plugin (5 tools)
- `service_status` — Unit status (systemctl status/is-active)
- `failed_units` — Failed units list
- `service_logs` — Service logs via journalctl -u
- `boot_analysis` — Boot time analysis (systemd-analyze blame)
- `service_ip_filter` — Effective IP filter: unit files + eBPF/bpftool (ground truth)

### Netdiag Plugin (6 tools)
- `http_check` — HTTP(S) check: status, timings, redirects
- `tls_check` — TLS certificate: expiry, chain, issuer
- `dns_resolve` — DNS resolution A/AAAA
- `tcp_connect` — TCP connect with timing
- `tcp_connect_as` — TCP probe as service user, per-uid filters (requires privileged_tools)
- `tcpdump_probe` — Short tcpdump slice (requires privileged_tools)

### Kubernetes Plugin (6 tools)
- `k8s_pods` — Pods with phases and restarts
- `k8s_events` — Cluster/namespace events
- `k8s_logs` — Pod logs (kubectl logs)
- `k8s_describe` — Pod describe (conditions)
- `k8s_top` — Pod resources (kubectl top)
- `k8s_deployments` — Deployment status

### Prometheus Plugin (4 tools)
- `prom_query` — Instant PromQL query
- `prom_range` — Range query over period
- `prom_alerts` — Firing/pending alerts
- `prom_targets` — Scrape targets up/down

### Loki Plugin (3 tools)
- `log_search` — LogQL search over period
- `log_labels` — Label names/values
- `log_tail` — Recent lines by selector

### System Tools
- `system_health_check` — Health check of all plugins
- `get_diagnostic_context` — Full diagnostic context
- `get_summary` — Brief system status summary
- `diagnose_host` — Параллельный срез хоста: статистика, топ-процессы, диск, память,
  последние ошибки journalctl (плагин linux). Опциональный `host` — имя из `hosts:`.
- `diagnose_web_service` — Параллельный срез веб-сервиса: статус nginx, systemd-юнит,
  последние error-логи nginx, плюс `http_check`, если задан `url`.
  Опциональные `service_name` (по умолчанию `nginx`) и `host`.

    kubeconfig: null      # null = ~/.kube/config
    context: null         # null = current-context

  prometheus:

---


### Linux Plugin
- `linux_host_stats` — Статистика хоста: CPU, память, диск, загрузка
- `linux_processes` — Список запущенных процессов
- `linux_logs` — Чтение системных логов (journalctl, syslog)
- `linux_network` — Сетевые интерфейсы, порты, соединения
- `linux_firewall` — Firewall snapshot: nftables + policy routing (read-only)
- `linux_disk` — Использование диска и файловых систем
- `linux_memory` — Детальная информация об использовании памяти
- `linux_execute_command` — Выполнение произвольной read-only команды

### Nginx Plugin
- `nginx_status` — Статус службы Nginx и процессов
- `nginx_logs` — Чтение error и access логов
- `nginx_config` — Проверка конфигурации Nginx
- `nginx_upstream` — Upstream: конфиг + реальный HTTP health check
- `nginx_stub_status` — Метрики stub_status: connections, requests

### Docker Plugin
- `docker_containers` — Список контейнеров с фильтрацией
- `docker_logs` — Логи контейнера
- `docker_stats` — Статистика контейнера: CPU, память, сеть
- `docker_info` — Полная информация о контейнере или системе
- `docker_events` — Docker события
- `docker_system_df` — Использование диска Docker
- `docker_prune` — Просмотр кандидатов; удаление только с `execute=true` и `confirm=true`

### PostgreSQL Plugin
- `pg_connections` — Активные подключения
- `pg_locks` — Блокировки и заблокированные запросы
- `pg_slow_queries` — Медленные запросы
- `pg_activity` — Полная активность: текущие запросы, состояния
- `pg_stats` — Статистика: таблицы, индексы, базы данных
- `pg_replication` — Статус репликации
- `pg_tables` — Список таблиц с размерами и статистикой

### Redis Plugin
- `redis_ping` — Доступность Redis (PING)
- `redis_info` — Секции INFO: memory, clients, stats, replication
- `redis_clients` — Клиентские подключения (CLIENT LIST)
- `redis_slowlog` — Slow log (SLOWLOG GET)
- `redis_memory` — Анализ памяти: used, peak, fragmentation, evictions

### Systemd Plugin
- `service_status` — Статус юнита (systemctl status/is-active)
- `failed_units` — Список failed юнитов
- `service_logs` — Логи сервиса через journalctl -u
- `boot_analysis` — Анализ времени загрузки (systemd-analyze blame)
- `service_ip_filter` — Эффективный IP-фильтр: unit-файлы + eBPF/bpftool

### Netdiag Plugin
- `http_check` — HTTP(S) проверка: статус, тайминги, редиректы
- `tls_check` — TLS сертификат: срок, chain, issuer
- `dns_resolve` — DNS резолвинг A/AAAA
- `tcp_connect` — TCP connect с замером времени
- `tcp_connect_as` — TCP-проба от имени сервис-юзера, per-uid фильтры (нужен privileged_tools)
- `tcpdump_probe` — Короткий tcpdump-срез (нужен privileged_tools)

### Kubernetes Plugin
- `k8s_pods` — Поды с фазами и рестартами
- `k8s_events` — События кластера/неймспейса
- `k8s_logs` — Логи пода (kubectl logs)
- `k8s_describe` — Describe пода (conditions)
- `k8s_top` — Ресурсы подов (kubectl top)
- `k8s_deployments` — Статус деплойментов

### Prometheus Plugin
- `prom_query` — Instant PromQL запрос
- `prom_range` — Range query за период
- `prom_alerts` — Активные алерты (firing/pending)
- `prom_targets` — Статус scrape targets (up/down)

### Loki Plugin
- `log_search` — LogQL поиск по логам за период
- `log_labels` — Список label names/values
- `log_tail` — Последние строки по селектору

---

## Architecture / Архитектура


```
mcp-linx/
├── src/mcp_linx/
│   ├── main.py               # Точка входа MCP сервера (FastMCP + AgentLoop)
│   ├── harness/              # Ядро Harness: agent_loop, plugin_manager (автообнаружение),
│   │                         #   context (компакция — библиотечный API)
│   ├── multihost.py          # HostRegistry — именованные удалённые хосты (`hosts:`)
│   ├── context_aggregator.py # Корреляции между компонентами
│   ├── security.py           # SecurityGuard (валидация команд, readonly режим)
│   ├── types.py              # Общие типы: Status, ToolResult, ComponentState, Correlation
│   ├── adapters/
│   │   ├── base.py           # Базовый адаптер (abstract) + LocalAdapter
│   │   ├── ssh.py            # SSH адаптер (paramiko)
│   │   ├── ssh_pool.py       # SSHConnectionPool + RemoteHostAdapter (мультихост)
│   │   └── docker.py         # Docker API адаптер
│   └── plugins/              # Автообнаружаемые плагины (10 всего, 56 инструментов)
│       ├── base.py           # Базовый DiagnosticPlugin (+ резолв `host`)
│       ├── linux/            # 8 инструментов
│       ├── nginx/            # 5 инструментов
│       ├── docker/           # 7 инструментов
│       ├── postgres/         # 7 инструментов
│       ├── redis/            # 5 инструментов
│       ├── systemd/          # 5 инструментов
│       ├── netdiag/          # 6 инструментов
│       ├── kubernetes/       # 6 инструментов
│       ├── prometheus/       # 4 инструмента
│       └── loki/             # 3 инструмента
├── config/settings.yaml      # Конфигурация сервера
├── tests/                    # Unit + интеграционные тесты; см. Тестирование
├── REMOTE_TROUBLESHOOTING.md   # Роадмап remote/SSH
└── docs/                     # ARCHITECTURE.md, DEVELOPMENT.md, SKILLS.md,
                              #   INCIDENT_504.md, skills/
```

Основные возможности:
- **Идеология Harness**: диагностические плагины обнаруживаются в `src/mcp_linx/plugins/`; agent loops, песочницы и компакторы контекста — отдельные компоненты harness.
- **Безопасность**: readonly-режим блокирует write-команды (rm, mkfs, dd, fork-бомбы и т.п.)
- **Context Aggregator**: находит корреляции между компонентами
- **Адаптеры**: Local subprocess, SSH (paramiko), Docker API
- **Мультихост**: именованные удалённые хосты в `hosts:`; `linux_*`, `nginx_*` (кроме `nginx_stub_status`) и `systemd_*` принимают аргумент `host` — см. `REMOTE_TROUBLESHOOTING.md`

---

## Testing / Тестирование

```bash
# Запуск всех тестов
pytest tests/ -v

# Запуск конкретного теста
pytest tests/unit/test_security.py -v
pytest tests/unit/test_new_plugins.py -v
```

---

## Security / Безопасность


Rate limiting применяется к обработчикам плагинных инструментов; системные
инструменты (`get_diagnostic_context`, `get_summary`, `system_health_check`,
`diagnose_host`, `diagnose_web_service`) регистрируются отдельно и лимитом не
покрываются. `diagnose_*` вызывают инструменты плагинов напрямую, поэтому их
внутренние вызовы не лимитируются и не аудируются по отдельности.
Отказы лимита не аудируются.

SecurityGuard обеспечивает:
- **Read-only режим**: Валидация команд блокирует команды записи (rm, write, mkfs, dd
  и др.) для командных адаптеров и инструментов. Некомандные write-пути тоже закрыты:
  `docker_prune` отказывается удалять при `readonly: true` (проверка `confirm` —
  дополнительный независимый барьер).
- **Блокировка опасных команд**: rm -rf /, mkfs, dd if=/dev/zero, fork bombs и др.
- **Ограничение размера вывода**: Обрезка больших результатов
- **Ограничение логов**: Максимальное количество строк
- **Валидация хостов**: Linux, Nginx и Systemd проверяют явный `host` по
  `security.allowed_hosts` до выбора адаптера. Проверяются имена реестра, не IP:
  опишите имя в `hosts:` и включите его в allowlist. Пустой allowlist отключает
  это ограничение. Это не универсальный сетевой ACL для API-клиентов и probe-целей.
- **Валидация входных данных**: MCP-обработчики принимают словарь `params`;
  поля проверяют отдельные инструменты, выделенных Pydantic-схем для каждого нет.

---

## Context Aggregator / Контекстный агрегатор


ContextAggregator анализирует состояния всех компонентов и выявляет корреляции:
- **Docker + Nginx**: Если Docker контейнеры падают, Nginx может не иметь апстримов
- **PostgreSQL + Docker**: Если PostgreSQL в контейнере и падает
- **Linux + компоненты**: Если Linux в критическом состоянии, другие компоненты могут не работать
- **OOM events**: Если Linux сообщает о OOM, это может объяснять падения контейнеров
- **Redis + PostgreSQL**: Вытеснение ключей в Redis при медленном PostgreSQL — каскад cache-miss
- **Linux + Kubernetes**: Поды OOMKilled при нехватке памяти на хосте
- **Netdiag + Nginx**: Проблема TLS сертификата при падении Nginx

---

## License / Лицензия
В метаданных пакета заявлена MIT. Отдельный файл `LICENSE` пока отсутствует;
текст лицензии и сведения о правообладателе остаются открытыми (TODO C1).
