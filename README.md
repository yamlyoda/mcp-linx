# MCP-Linx — MCP Server for Linux Infrastructure Diagnostics

**English:** MCP-Linx is an MCP (Model Context Protocol) server for Linux infrastructure diagnostics. It provides tools for monitoring and diagnosing components: Linux host, Nginx, Docker, PostgreSQL.

**Русский:** MCP-Linx — это MCP (Model Context Protocol) сервер для диагностики Linux-инфраструктуры. Он предоставляет инструменты для мониторинга и диагностики компонентов: Linux host, Nginx, Docker, PostgreSQL.

---

## Installation / Установка

**English:**
```bash
# Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

**Русский:**
```bash
# Создание виртуального окружения
python3.11 -m venv .venv
source .venv/bin/activate

# Установка зависимостей
pip install -e ".[dev]"
```

---

## Running the Server / Запуск сервера

**English:**
```bash
# Start MCP server (stdio mode)
python -m mcp_linx.main

# With MCP Inspector for debugging
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

**Русский:**
```bash
# Запуск MCP сервера (stdio режим)
python -m mcp_linx.main

# С запуском MCP Inspector для отладки
npx @modelcontextprotocol/inspector python -m mcp_linx.main
```

---

## Configuration / Конфигурация

**English:** Main configuration file: `config/settings.yaml`

**Русский:** Основной конфигурационный файл: `config/settings.yaml`

```yaml
environment:
  mode: development
  debug: true

security:
  readonly: true                    # Only read-only operations / Только read-only операции
  max_command_output_size: 10000    # Maximum command output size / Максимальный размер вывода команды
  max_log_lines: 500
  command_timeout_seconds: 30
  allowed_hosts:
    - "localhost"
    - "127.0.0.1"

plugins:
  enabled:
    - linux
    - nginx
    - docker
    - postgres
  linux:
    ssh:
      host: null                    # null = localhost / localhost
  nginx:
    log_path: "/var/log/nginx"
  docker:
    host: "unix:///var/run/docker.sock"
  postgres:
    host: "localhost"
    port: 5432
    database: "postgres"
```

---

## Tools / Инструменты

**English:**

### Linux Plugin (7 tools)
- `linux_host_stats` — Host statistics: CPU, memory, disk, load
- `linux_processes` — List of running processes
- `linux_logs` — Read system logs (journalctl, syslog)
- `linux_network` — Network interfaces, ports, connections
- `linux_disk` — Disk and filesystem usage
- `linux_memory` — Detailed memory usage information
- `linux_execute_command` — Execute an arbitrary read-only command

### Nginx Plugin (4 tools)
- `nginx_status` — Nginx service status and processes
- `nginx_logs` — Read error and access logs
- `nginx_config` — Nginx configuration check
- `nginx_upstream` — Upstream server status

### Docker Plugin (6 tools)
- `docker_containers` — List containers with filtering
- `docker_logs` — Container logs
- `docker_stats` — Container stats: CPU, memory, network
- `docker_info` — Full container or system info
- `docker_events` — Docker events
- `docker_system_df` — Docker disk usage

### PostgreSQL Plugin (7 tools)
- `pg_connections` — Active connections
- `pg_locks` — Locks and blocked queries
- `pg_slow_queries` — Slow queries
- `pg_activity` — Full activity: current queries, states, waits
- `pg_stats` — Statistics: tables, indexes, databases
- `pg_replication` — Replication status (if configured)
- `pg_tables` — List of tables with sizes and statsries, states
- `pg_stats` — Statistics: tables, indexes, databases
- `pg_replication` — Replication status
- `pg_tables` — List tables with sizes and statistics

### System Tools
- `system_health_check` — Health check of all plugins
- `get_diagnostic_context` — Full diagnostic context
- `get_config` — Current server configurationries, states
- `pg_stats` — Statistics: tables, indexes, databases
- `pg_replication` — Replication status
- `pg_tables` — List tables with sizes and statistics

### System Tools
- `system_health_check` — Health check of all plugins
- `get_diagnostic_context` — Full diagnostic context
- `get_config` — Current server configuration

---

**Русский:**

### Linux Plugin
- `linux_host_stats` — Статистика хоста: CPU, память, диск, загрузка
- `linux_processes` — Список запущенных процессов
- `linux_logs` — Чтение системных логов (journalctl, syslog)
- `linux_network` — Сетевые интерфейсы, порты, соединения
- `linux_disk` — Использование диска и файловых систем
- `linux_memory` — Детальная информация об использовании памяти
- `linux_execute_command` — Выполнение произвольной read-only команды

### Nginx Plugin
- `nginx_status` — Статус службы Nginx и процессов
- `nginx_logs` — Чтение error и access логов
- `nginx_config` — Проверка конфигурации Nginx
- `nginx_upstream` — Статус upstream серверов

### Docker Plugin
- `docker_containers` — Список контейнеров с фильтрацией
- `docker_logs` — Логи контейнера
- `docker_stats` — Статистика контейнера: CPU, память, сеть
- `docker_info` — Полная информация о контейнере или системе
- `docker_events` — Docker события
- `docker_system_df` — Использование диска Docker

### PostgreSQL Plugin
- `pg_connections` — Активные подключения
- `pg_locks` — Блокировки и заблокированные запросы
- `pg_slow_queries` — Медленные запросы
- `pg_activity` — Полная активность: текущие запросы, состояния
- `pg_stats` — Статистика: таблицы, индексы, базы данных
- `pg_replication` — Статус репликации
- `pg_tables` — Список таблиц с размерами и статистикой

### Системные инструменты
- `system_health_check` — Health check всех плагинов
- `get_diagnostic_context` — Полный диагностический контекст
- `get_config` — Текущая конфигурация сервера

## Architecture / Архитектура

**English:**

```
mcp_linx/
├── src/mcp_linx/
│   ├── main.py              # MCP server entry point (FastMCP)
│   ├── plugin_manager.py    # Plugin registration and lifecycle
│   ├── context_aggregator.py # Context aggregator (cross-component correlations)
│   ├── security.py          # SecurityGuard (command validation, readonly mode)
│   ├── types.py             # Shared types: Status, ToolResult, ComponentState, Correlation
│   ├── adapters/
│   │   ├── base.py          # Base adapter (abstract)
│   │   ├── ssh.py           # SSH adapter (paramiko)
│   │   └── docker.py        # Docker API adapter
│   └── plugins/
│       ├── base.py          # Base DiagnosticPlugin
│       ├── linux.py         # Linux plugin + linux/tools.py (9 tools)
│       ├── nginx.py         # Nginx plugin + nginx/tools.py (5 tools)
│       ├── docker.py        # Docker plugin + docker/tools.py (6 tools)
│       ├── postgres.py      # PostgreSQL plugin + postgres/tools.py (9 tools)
├── config/settings.yaml     # Server configuration
└── tests/                   # Unit tests (25 tests, all passing)
```

Key features:
- **Security**: Readonly mode blocks write commands (rm, mkfs, dd, fork bombs, etc.)
- **Context Aggregator**: Detects correlations — Docker+Nginx, OOM events, PostgreSQL+Docker, Linux cascades
- **Adapters**: Local subprocess, SSH (paramiko), Docker API

**Русский:**

```
mcp_linx/
├── src/mcp_linx/
│   ├── main.py              # Точка входа MCP сервера (FastMCP)
│   ├── plugin_manager.py    # Регистрация и жизненный цикл плагинов
│   ├── context_aggregator.py # Агрегатор контекста (корреляции между компонентами)
│   ├── security.py          # SecurityGuard (валидация команд, readonly режим)
│   ├── types.py             # Общие типы: Status, ToolResult, ComponentState, Correlation
│   ├── adapters/
│   │   ├── base.py          # Базовый адаптер (abstract)
│   │   ├── ssh.py           # SSH адаптер (paramiko)
│   │   └── docker.py        # Docker API адаптер
│   └── plugins/
│       ├── base.py          # Базовый DiagnosticPlugin
│       ├── linux.py         # Linux плагин + linux/tools.py (7 инструментов)
│       ├── nginx.py         # Nginx плагин + nginx/tools.py (4 инструмента)
│       ├── docker.py        # Docker плагин + docker/tools.py (6 инструментов)
│       ├── postgres.py      # PostgreSQL плагин + postgres/tools.py (7 инструментов)
├── config/settings.yaml     # Конфигурация сервера
└── tests/                   # Unit тесты (25 тестов, все проходят)
```

Основные возможности:
- **Безопасность**: Readonly режим блокирует команды записи (rm, mkfs, dd, fork bombs и др.)
- **Контекстный агрегатор**: Выявляет корреляции — Docker+Nginx, OOM события, PostgreSQL+Docker, каскады от Linux
- **Адаптеры**: Локальный subprocess, SSH (paramiko), Docker API

---

## Testing / Тестирование

**English:**
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_security.py -v
pytest tests/unit/test_context_aggregator.py -v
```

**Русский:**
```bash
# Запуск всех тестов
pytest tests/ -v

# Запуск конкретного теста
pytest tests/unit/test_security.py -v
pytest tests/unit/test_context_aggregator.py -v
```

---

## Security / Безопасность

**English:**

SecurityGuard provides:
- **Read-only mode**: Blocks write commands (rm, write, mkfs, dd and others)
- **Dangerous command blocking**: rm -rf /, mkfs, dd if=/dev/zero, fork bombs etc.
- **Output size limiting**: Truncates large command outputs
- **Log line limiting**: Maximum number of log lines returned
- **Host validation**: Whitelist of allowed_hosts
- **Input validation**: Pydantic schemas for all tool inputs

**Русский:**

SecurityGuard обеспечивает:
- **Read-only режим**: Блокировка команд записи (rm, write, mkfs, dd и др.)
- **Блокировка опасных команд**: rm -rf /, mkfs, dd if=/dev/zero, fork bombs и др.
- **Ограничение размера вывода**: Truncation больших результатов
- **Ограничение логов**: Максимальное количество строк
- **Валидация хостов**: Whitelist allowed_hosts
- **Валидация входных данных**: Pydantic схемы для всех входных данных инструментов

---

## Context Aggregator / Контекстный агрегатор

**English:**

ContextAggregator analyzes states of all components and detects correlations:
- **Docker + Nginx**: If Docker containers are down, Nginx may have no upstreams
- **PostgreSQL + Docker**: If PostgreSQL is in a container and failing
- **Linux + components**: If Linux is in critical state, other components may fail
- **OOM events**: Linux OOM messages may explain container crashes

**Русский:**

ContextAggregator анализирует состояния всех компонентов и выявляет корреляции:
- **Docker + Nginx**: Если Docker контейнеры падают, Nginx может не иметь апстримов
- **PostgreSQL + Docker**: Если PostgreSQL в контейнере и падает
- **Linux + компоненты**: Если Linux в критическом состоянии, другие компоненты могут не работать
- **OOM events**: Если Linux сообщает о OOM, это может объяснять падения контейнеров

---

## License / Лицензия

MIT
