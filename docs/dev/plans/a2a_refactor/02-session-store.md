# Шаг 02 — SessionStore: состояние инструментов в MCP

**Цель.** Дать MCP-server модель сессий, без которой половина каталога
неработоспособна.

**Предусловия.** Шаг 01 завершён.

**Оценка.** 0.5 дня.

---

## Зачем это вообще нужно

Инструменты не stateless. `load_blocks()` кладёт GeoDataFrame в `state`,
`compute_service_provision("school")` — результат в `state["provision_school"]`,
а `get_analysis_results("provision_school")`, `get_metric_for_block(...)`,
`render_metric_map(...)`, `list_cached_data()` его оттуда **читают**.

Если MCP-server создаст один `state` на процесс — два параллельных клиента
затрут данные друг друга и увидят чужой кэш. Если создавать `state` на каждый
вызов — многошаговые сценарии не заработают вовсе («Кэш пуст. Загрузи данные
с помощью load_blocks()»).

Решение — [../../decisions/open_questions.md](../../decisions/open_questions.md) Q4: явный `session_id`.

---

## Задачи

### 2.1. `blocksnet_mcp/session.py` — новый файл

```python
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Session:
    session_id: str
    state: dict[str, Any] = field(default_factory=dict)
    data_dir: Path | None = None      # None → берётся из настроек
    output_dir: Path | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    meta: dict[str, Any] = field(default_factory=dict)   # scenario_id/project_id — шаг 06


class SessionStore:
    """Хранилище сессий MCP: session_id -> изолированный state инструментов.

    В памяти процесса. TTL — против утечки GeoDataFrame'ов, LRU — против
    неограниченного роста при множестве клиентов.
    """

    def __init__(self, ttl_sec: float = 1800.0, max_sessions: int = 8) -> None: ...

    def get_or_create(self, session_id: str | None) -> Session: ...
    def get(self, session_id: str) -> Session | None: ...
    def close(self, session_id: str) -> bool: ...
    def info(self, session_id: str | None = None) -> dict[str, Any]: ...
    def sweep(self) -> int:
        """Удаляет протухшие по TTL. Вызывается перед каждым get_or_create."""
```

Требования:

- **потокобезопасность**: `threading.RLock` вокруг всех операций —
  FastMCP исполняет инструменты в пуле потоков;
- `get_or_create(None)` и `get_or_create("default")` дают одну и ту же
  сессию `"default"` (однопользовательский сценарий без изменений у клиента);
- новый id: `f"s-{uuid.uuid4().hex[:8]}"`;
- вытеснение: при превышении `max_sessions` закрывается сессия с наименьшим
  `last_used_at`, **кроме** `"default"`;
- `close()` вызывает `session.state.clear()` — GeoDataFrame'ы должны
  освобождаться явно, не ждать GC;
- `info()` возвращает `{session_id, age_sec, idle_sec, keys: [...], n_keys}`;
  `keys` — только имена, **не** содержимое (там DataFrame'ы);
- ни одного импорта из `blocksnet_agent` в этом модуле.

### 2.2. Настройки

В `blocksnet_mcp/settings.py` добавить (шаг 03 переработает файл целиком,
здесь только поля):

```python
session_ttl_sec: float = Field(default=1800.0, validation_alias="SESSION_TTL_SEC")
max_sessions: int = Field(default=8, validation_alias="MAX_SESSIONS")
```

### 2.3. Синглтон стора

```python
@lru_cache(maxsize=1)
def get_session_store() -> SessionStore: ...
```

Читает TTL/лимит из настроек. Отдельная функция `reset_session_store()`
для тестов (сбрасывает кэш `lru_cache`).

---

## Тесты — `tests/test_mcp_session.py`

```python
def test_default_session_is_stable():
    store = SessionStore()
    assert store.get_or_create(None) is store.get_or_create("default")

def test_sessions_are_isolated():
    store = SessionStore()
    a, b = store.get_or_create("a"), store.get_or_create("b")
    a.state["blocks"] = "X"
    assert "blocks" not in b.state

def test_ttl_expires_session():
    store = SessionStore(ttl_sec=0.01)
    sid = store.get_or_create(None).session_id
    time.sleep(0.05)
    store.sweep()
    assert store.get(sid) is None

def test_lru_evicts_oldest_but_never_default():
    store = SessionStore(max_sessions=2)
    store.get_or_create("default")
    first = store.get_or_create(None).session_id
    store.get_or_create(None)
    assert store.get("default") is not None
    assert store.get(first) is None

def test_close_clears_state():
    store = SessionStore()
    s = store.get_or_create("x")
    s.state["blocks"] = object()
    store.close("x")
    assert s.state == {}

def test_info_does_not_leak_values():
    store = SessionStore()
    store.get_or_create("x").state["blocks"] = "secret"
    assert "secret" not in json.dumps(store.info("x"))

def test_thread_safety_under_concurrent_create():
    """20 потоков создают сессии — стор не рассыпается, лимит соблюдён."""
```

Тайминги через `time.monotonic` (не `time.time`) — тест не должен зависеть
от системных часов.

---

## DoD

- [ ] `blocksnet_mcp/session.py` создан, импортов из `blocksnet_agent` нет
      (`grep blocksnet_agent blocksnet_mcp/session.py` — пусто)
- [ ] `python -m pytest tests/test_mcp_session.py -q` — зелёный
- [ ] `python -m pytest -q` — не хуже baseline
- [ ] Коммит `a2a/02: session store for MCP tool state`

## Не делать

- Не хранить в сессии ничего, кроме `state` и метаданных: артефакты — на
  диске в `OUTPUT_DIR`.
- Не делать TTL нулевым/бесконечным по умолчанию — GeoDataFrame кварталов
  плюс матрица доступности занимают сотни мегабайт.
- Не сериализовать сессии на диск: v2.0 — только память (Q4, ограничение).
- Не привязывать сессию к MCP-соединению: это ломает будущий HTTP-транспорт.

## Откат

Удалить `session.py` и тест, откатить поля в `settings.py`. Ни один другой
модуль на этом шаге не затронут.
