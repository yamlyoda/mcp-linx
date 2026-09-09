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

| Принцип | Статус | Проблема |
|---------|--------|----------|
| Агентный цикл как плагин | ❌ Нет | `main.py` захардкожен |
| Автообнаружение плагинов | ❌ Нет | Ручной импорт в `main.py` |
| Песочница как плагин | ❌ Нет | Нет концепции sandbox |
| Компакция контекста | ❌ Нет | Не реализовано |
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
    async def run(self, mcp, plugins, config):
        ...

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
                if isinstance(attr, type) and issubclass(attr, DiagnosticPlugin) and attr != DiagnosticPlugin:
                    register_plugin(attr)
```

---

### 3. Песочница как плагин (MEDIUM)

**Текущее состояние**: Нет концепции песочницы.

**Требование Harness**: Изоляция выполнения кода.

**Решение**:
```python
class Sandbox(ABC):
    @abstractmethod
    async def execute(self, command: str) -> dict:
        ...

class LocalSandbox(Sandbox):
    async def execute(self, command: str) -> dict:
        # Локальное выполнение
        ...

class DockerSandbox(Sandbox):
    async def execute(self, command: str) -> dict:
        # Выполнение в контейнере
        ...
```

---

### 4. Компакция контекста (MEDIUM)

**Текущее состояние**: Не реализовано.

**Требование Harness**: Управление размером контекста для длинных сессий.

**Решение**:
```python
class ContextCompactor(ABC):
    @abstractmethod
    def compact(self, messages: list) -> list:
        ...

class SlidingWindowCompactor(ContextCompactor):
    def __init__(self, max_messages: int = 50):
        self.max_messages = max_messages
    
    def compact(self, messages: list) -> list:
        return messages[-self.max_messages:]
```

---

## Оценка соответствия Harness

| Критерий | Вес | Оценка | Комментарий |
|----------|-----|--------|-------------|
| Плагин-архитектура | 20% | 90% | Базовая архитектура есть |
| Config-driven | 15% | 80% | Конфиг есть, но не всё через него |
| Автообнаружение | 15% | 0% | Ручной импорт |
| Агентный цикл | 15% | 10% | Захардкожен |
| Песочница | 10% | 0% | Нет |
| Компакция контекста | 10% | 0% | Нет |
| Сабагенты | 10% | 0% | Нет |
| Документация | 5% | 50% | Базовая есть |

**Итого: 35%** — проект имеет базовую плагин-архитектуру, но требует доработки для полного соответствия Harness.

---

## План миграции на Harness

### Фаза 1: Автообнаружение плагинов
- [ ] Реализовать `discover_plugins()` в `PluginManager`
- [ ] Убрать ручной импорт из `main.py`
- [ ] Добавить тесты на автопоиск

### Фаза 2: Агентный цикл как плагин
- [ ] Вынести логику из `main.py` в `DefaultAgentLoop`
- [ ] Добавить интерфейс `AgentLoop`
- [ ] Сделать выбор цикла через конфиг

### Фаза 3: Песочница
- [ ] Добавить интерфейс `Sandbox`
- [ ] Реализовать `LocalSandbox` и `DockerSandbox`
- [ ] Интегрировать с плагинами

### Фаза 4: Компакция контекста
- [ ] Добавить интерфейс `ContextCompactor`
- [ ] Реализовать базовые стратегии
- [ ] Добавить в конфиг
