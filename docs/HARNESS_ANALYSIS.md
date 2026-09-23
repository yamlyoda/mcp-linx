# Harness Ideology Analysis — MCP-Linx

## Что такое Harness (из статьи на Хабре)

**Harness** — это обвязка (wrapper) вокруг AI-модели, которая превращает её из "текст → текст" в полноценного агента.

Ключевая философия: **"Everything is a plugin"**
- Модели, инструменты, скиллы, сессии, песочницы, файловые системы, агентный цикл, оркестрация, интерфейс — всё плагины
- Смена компонентов через конфиг без правки исходников
- Результат = Модель + Harness (а не только модель)

---

## Текущее состояние проекта

### ✅ Что соответствует Harness

| Принцип | Статус | Реализация |
|---------|--------|------------|
| Плагин-архитектура | ✅ Есть | `PluginManager`, `register_plugin()`, `DiagnosticPlugin` |
| Config-driven | ✅ Есть | `settings.yaml` управляет плагинами |
| Инструменты как плагины | ✅ Есть | Каждый плагин предоставляет tools |
| Стандартизированный интерфейс | ✅ Есть | `DiagnosticPlugin` базовый класс |
| Инициализация/деинициализация | ✅ Есть | `initialize()`, `destroy()` |
| Health check | ✅ Есть | `health_check()` |

### ❌ Что НЕ соответствует Harness

> **Актуализировано 2026-09-18** (раньше здесь стоял статус на момент аудита).
> Реализовано: агентный цикл (`AgentLoop`/`DefaultAgentLoop`/`StreamingAgentLoop`,
> выбор через env `AGENT_LOOP`), автообнаружение (`discover_plugins()` в `main.py`).
> Отклонено: песочница (мёртвый `harness/sandbox.py` удалён — не вызывался нигде).

| Принцип | Статус | Комментарий |
|---------|--------|-------------|
| Агентный цикл как плагин | ✅ Есть | `harness/agent_loop.py`; выбор через `AGENT_LOOP` |
| Автообнаружение плагинов | ✅ Есть | `discover_plugins()` сканирует `src/mcp_linx/plugins/` |
| Песочница как плагин | ⛔ Отклонено | `sandbox.py` удалён (2026-09-18): 0 вызовов, только реэкспорт |
| Компакция контекста | 🟡 Резерв | Интерфейс + 3 реализации в `harness/context.py`, но в `agent_loop` не подключены: историю диалога ведёт MCP-клиент, сервер её не хранит |
| Сабагенты | ❌ Нет | Нет поддержки |
| Зависимости между плагинами | ❌ Нет | Нет управления зависимостями |
| Hot-reload плагинов | ❌ Нет | Нет перезагрузки без рестарта |

---

## Детальный анализ

### 1. Агентный цикл (CRITICAL)

**Текущее состояние**: `main.py` содержит захардкоженный цикл:
```python
# main.py
mcp = FastMCP(...)
_register_tools(mcp, plugin_manager, ...)
await plugin_manager.initialize_all()
await mcp.run_async()
```

**Требование Harness**: Агентный цикл должен быть плагином, который можно заменить через конфиг.

**Решение**:
```python
# Вместо хардкода в main.py
class AgentLoop(ABC):
    @abstractmethod
    async def run(self, mcp, plugins, config): ...


class DefaultAgentLoop(AgentLoop):
    async def run(self, mcp, plugins, config):
        # Стандартная логика
        ...
```

---

### 2. Автообнаружение плагинов (HIGH)

**Текущее состояние**: Ручной импорт в `main.py`:
```python
from mcp_linx.plugins.linux import LinuxPlugin
from mcp_linx.plugins.nginx import NginxPlugin

# ...
register_plugin(LinuxPlugin)
register_plugin(NginxPlugin)
```

**Требование Harness**: Плагины должны обнаруживаться автоматически.

**Решение**: Использовать `importlib` для автопоиска:
```python
# plugin_manager.py
def discover_plugins():
    """Автообнаружение плагинов в директории plugins/"""
    plugins_dir = Path(__file__).parent / "plugins"
    for plugin_dir in plugins_dir.iterdir():
        if plugin_dir.is_dir() and (plugin_dir / "__init__.py").exists():
            module = importlib.import_module(f"mcp_linx.plugins.{plugin_dir.name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, DiagnosticPlugin)
                    and attr != DiagnosticPlugin
                ):
                    register_plugin(attr)
```

---

### 3. Песочница как плагин (MEDIUM) — ⛔ ОТКЛОНЕНО (2026-09-18)

**Решение**: песочница не реализуется. Модуль `harness/sandbox.py` содержал
`Sandbox` / `LocalSandbox` / `DockerSandbox` / `RemoteSandbox`, но не вызывался
ни из `agent_loop`, ни из плагинов — существовал только как реэкспорт в
`harness/__init__.py`. Изоляция выполнения обеспечивается иначе и уже сейчас:

- **Модель запуска A** — контейнер диагностирует удалённые хосты (SSH);
- **Модель запуска B** — `pid: host` / read-only маунты (см. `docker-compose.yml`);
- **`SecurityGuard`** — allowlist команд, `readonly`, лимиты вывода и логов.

Мёртвый модуль удалён, чтобы не создавать ложного впечатления реализованной
функциональности (тот же принцип, что A7/A10/A11). Если изоляция команд
понадобится как отдельный уровень, её следует проектировать вместе с точкой
подключения в `agent_loop`, а не держать неиспользуемый интерфейс.

---

### 4. Компакция контекста (MEDIUM)

**Текущее состояние**: Не реализовано.

**Требование Harness**: Управление размером контекста для длинных сессий.

**Решение**:
```python
class ContextCompactor(ABC):
    @abstractmethod
    def compact(self, messages: list) -> list: ...


class SlidingWindowCompactor(ContextCompactor):
    def __init__(self, max_messages: int = 50):
        self.max_messages = max_messages

    def compact(self, messages: list) -> list:
        return messages[-self.max_messages :]
```

---

## Оценка соответствия Harness

| Критерий | Вес | Оценка | Комментарий |
|----------|-----|--------|-------------|
| Плагин-архитектура | 20% | 90% | Базовая архитектура есть |
| Config-driven | 15% | 85% | Конфиг есть; состав плагинов через `plugins.enabled` |
| Автообнаружение | 15% | 100% | `discover_plugins()`, тесты на счётчики |
| Агентный цикл | 15% | 80% | `AgentLoop` + выбор через `AGENT_LOOP` (streaming — без отдельной реализации) |
| Песочница | 10% | 0% | ⛔ Отклонено: `sandbox.py` удалён как мёртвый |
| Компакция контекста | 10% | 40% | Реализации есть и покрыты, но в `agent_loop` не подключены |
| Сабагенты | 10% | 0% | Нет |
| Документация | 5% | 90% | README EN/RU, docs/, INDEX со тестом-стражем |

**Итого: ~65%** (пересчитано 2026-09-18; ранее 35%). Незакрытые пункты —
сабагенты (вне текущей задачи проекта) и подключение компакторов (нет потребителя:
историю диалога ведёт MCP-клиент).

---

## План миграции на Harness (статус 2026-09-18)

### Фаза 1: Автообнаружение плагинов — ✅ ГОТОВО
- [x] `discover_plugins()` в `plugin_manager.py`
- [x] Ручной импорт убран из `main.py` (`main.py:112`)
- [x] Тесты: `test_discovery.py` (точные счётчики), `test_plugin_manager.py`

### Фаза 2: Агентный цикл как плагин — ✅ ГОТОВО
- [x] Логика вынесена в `DefaultAgentLoop`
- [x] Интерфейс `AgentLoop`
- [x] Выбор цикла через env `AGENT_LOOP` (`main.py:95-103,128`)

### Фаза 3: Песочница — ⛔ ОТКЛОНЕНО (2026-09-18)
- [x] Интерфейс `Sandbox` существовал, но не использовался → модуль удалён
- [~] `LocalSandbox` / `DockerSandbox` — не реализуем: изоляция обеспечивается
  моделью запуска контейнера (см. раздел 3 выше)

### Фаза 4: Компакция контекста — 🟡 ЧАСТИЧНО (осознанный резерв)
- [x] Интерфейс `ContextCompactor` + три реализации (`SlidingWindow`, `TokenLimit`,
  `Summary`) в `harness/context.py`, покрыты `tests/unit/test_context_compactors.py`
- [~] В `agent_loop` не подключены: сервер не хранит историю диалога (её ведёт
  MCP-клиент), поэтому подключать нечего — компонент остаётся библиотечным API
- [x] Ключи конфига для компакции не вводим, пока нет потребителя (иначе это были бы
  мёртвые ключи — см. A7/A10/A11)
