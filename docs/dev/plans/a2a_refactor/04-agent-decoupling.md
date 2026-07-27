# Шаг 04 — Подготовка агента к конкурентности

**Цель.** Снять два препятствия, из-за которых A2A-сервис не сможет
обслуживать задачи параллельно и будет иметь три копии настроек.

**Предусловия.** Шаг 01. Независим от 02–03 (параллельная ветка).

**Оценка.** 0.5 дня.

---

## 4.1. Стоп-флаг: из глобального в per-run

### Проблема

`blocksnet_agent/runtime.py`:

```python
_stop_event = threading.Event()   # один на процесс
def stop_run():        _stop_event.set()
def is_stop_requested(): return _stop_event.is_set()
```

`is_stop_requested()` читают **все** инструменты
(`blocksnet_agent/tools/__init__.py`, обёртка `wrapped_call`). В A2A-сервисе
с несколькими одновременными задачами дедлайн или отмена одной остановит все
остальные: они получат `"STOP: запуск прерван по дедлайну"` на следующем же
вызове инструмента.

`RunContext` уже живёт в `ContextVar` и изолирован между задачами — стоп-флагу
место там же.

### Решение

1. Добавить в `RunContext` поле `stop_event: threading.Event`
   (создаётся в `__init__`).
2. `stop_run(...)` — взводит флаг **текущего** контекста; сохранить
   параметр `all_runs: bool = False` для shutdown-сценария (тогда взводится
   глобальный).
3. `is_stop_requested()` — возвращает `current_ctx.stop_event.is_set() or _global_stop.is_set()`;
   при отсутствии контекста — только глобальный. Сигнатура не меняется,
   вызывающие править не нужно.
4. `start_run()` — сбрасывает флаг **своего** контекста, а не глобальный
   (сейчас `_stop_event.clear()` на строке ~144 гасит чужие отмены).

### Важно про потоки

`ContextVar` не наследуется автоматически в `loop.run_in_executor` и в пуле
FastMCP. В `blocksnet_mcp/server.py` контекст уже прокидывается через
`start_run` внутри рабочего потока — сохранить этот паттерн и в A2A
(шаг 05): контекст создаётся **в том же потоке**, где исполняется агент.

### Тест — `tests/test_runtime_stop_scope.py`

```python
def test_stop_is_scoped_to_run():
    """Два прогона в разных потоках: остановка одного не трогает второй."""

def test_stop_all_runs_affects_everyone():
    stop_run(all_runs=True)

def test_start_run_does_not_clear_other_runs_stop():

def test_is_stop_requested_without_context_returns_global():
```

---

## 4.2. Единые настройки вместо трёх

### Проблема

`CHAT_URL`/`API_KEY`/`MODEL`/`MAX_ITERATIONS` объявлены дважды:
`blocksnet_agent/config.py` (`Settings`) и `blocksnet_mcp/settings.py`
(`MCPSettings`). Дефолт `max_iterations` уже задан в двух местах (24 и 24 —
пока совпадают, но синхронизируются вручную). Исходный план добавлял третью
копию в `a2a/settings.py`.

### Решение

- В шаге 03 из `MCPSettings` LLM-поля уже стали необязательными.
- На шаге 05 `A2ASettings` **наследует** `blocksnet_agent.config.Settings`
  и добавляет только транспортное: `port`, `host`, `auth_enabled`,
  `mas_bearer_token`, `task_ttl_sec`, `max_concurrent_tasks`.
- Здесь — только подготовка: убедиться, что `Settings` наследуема
  (`model_config` с `extra: "ignore"` — да, наследуется корректно),
  и добавить тест.

### Тест — `tests/test_settings_inheritance.py`

```python
def test_a2a_settings_inherit_agent_settings(monkeypatch):
    """Дефолты LLM берутся из одного места, не дублируются."""

def test_mcp_settings_start_without_llm(monkeypatch):
    """MCPSettings() создаётся без CHAT_URL/API_KEY."""
```

(Первый тест написать на шаге 05, когда появится `A2ASettings`; здесь —
второй.)

---

## 4.3. `blocksnet_agent/__main__.py`

Заготовка entrypoint; наполняется на шаге 05:

```python
from blocksnet_agent.a2a.server import main

if __name__ == "__main__":
    main()
```

До шага 05 — файл не создавать, чтобы не оставлять сломанный импорт.
Задача зафиксирована здесь, выполняется в 05.

---

## DoD

- [ ] `python -m pytest tests/test_runtime_stop_scope.py -q` — зелёный
- [ ] `python -m pytest -q` — не хуже baseline; особенно
      `tests/test_runtime.py` (проверяет текущее поведение runtime)
- [ ] `blocksnet_agent/agent.py`, `hypotheses.py`, `metrics.py` не изменены
- [ ] Сигнатуры `stop_run`/`is_stop_requested` обратно совместимы:
      `grep -rn "stop_run\|is_stop_requested" --include=*.py .` — все
      вызывающие работают без правок
- [ ] Коммит `a2a/04: per-run stop flag, settings deduplication`

## Не делать

- Не удалять глобальный стоп-флаг совсем: он нужен для остановки процесса
  целиком (shutdown, SIGTERM).
- Не менять сигнатуры существующих функций runtime — они вызываются из
  обёртки инструментов и из `server.py`.
- Не трогать логику дедлайнов (`is_deadline_reached`, `_finalize`) — она
  корректна и покрыта тестами.

## Откат

`git revert` коммита. Изменения локализованы в `runtime.py` и новых тестах.
