# Шаг 05 — A2A-агент: Agent Card, task lifecycle, два skill

**Цель.** `python -m blocksnet_agent` поднимает A2A-агента, отдающего Agent Card
и исполняющий `run_pipeline` / `analyze_urban_question`.

**Предусловия.** Шаг 00.6 (спайк, `spike-a2a.md` с точной версией SDK) и
шаг 04 (per-run стоп-флаг). Шаг 01 желателен, обязательным не является.

**Оценка.** 2 дня. Самый крупный шаг ветки агента.

---

## Ориентиры

- Все имена классов SDK, путь Agent Card и способ регистрации executor'а
  брать из `spike-a2a.md`, а **не** из этого файла: SDK меняется, спайк
  описывает фактическую версию.
- Весь код SDK — только внутри `blocksnet_agent/a2a/`. Ядро агента про A2A
  не знает (инвариант: `agent.py` не редактируется).
- Агент вызывает инструменты **in-process**. Никакого MCP-клиента внутри
  A2A-агента (см. [../../decisions/open_questions.md](../../decisions/open_questions.md) Q6 —
  это не оптимизация, а условие сохранения качества ответов).

## Структура пакета

```
blocksnet_agent/a2a/
├── __init__.py
├── __main__.py        # python -m blocksnet_agent.a2a
├── server.py          # сборка приложения + main()
├── agent_card.py      # карточка: skills, capabilities
├── executor.py        # мост A2A ↔ BlocksNetAgent
├── task_manager.py    # жизненный цикл задач
├── schemas.py         # pydantic: вход/выход skills
├── settings.py        # A2ASettings(Settings)
├── auth.py            # шаг 06
├── context.py         # шаг 06
└── skills/
    ├── __init__.py            # реестр skills
    ├── run_pipeline.py        # основная реализация
    └── analyze_urban_question.py   # обёртка (back-compat)
```

---

## Задачи

### 5.1. `settings.py`

```python
from blocksnet_agent.config import Settings

class A2ASettings(Settings):
    """Наследует CHAT_URL/API_KEY/MODEL/MAX_ITERATIONS — не дублирует их."""
    host: str = Field(default="0.0.0.0", validation_alias="A2A_HOST")
    port: int = Field(default=8080, validation_alias="A2A_PORT")
    public_url: str | None = Field(default=None, validation_alias="A2A_PUBLIC_URL")
    max_concurrent_tasks: int = Field(default=2, validation_alias="A2A_MAX_CONCURRENT_TASKS")
    task_ttl_sec: float = Field(default=3600.0, validation_alias="A2A_TASK_TTL_SEC")
    deadline_sec: int = Field(default=480, validation_alias="DEADLINE_SEC")
    # auth-поля — шаг 06
```

`max_concurrent_tasks=2` по умолчанию осознанно: каждая задача держит в
памяти GeoDataFrame кварталов и матрицу доступности.

### 5.2. `schemas.py`

```python
class RunPipelineInput(BaseModel):
    question: str
    max_iterations: int | None = None
    scenario_id: str | None = None     # шаг 06
    project_id: str | None = None      # шаг 06

class SkillOutput(BaseModel):
    """Тот же JSON, что отдаёт сегодня MCP-tool. Поля НЕ переименовывать."""
```

`SkillOutput` описывает результат `blocksnet_mcp.serialize.to_json()` +
`status`, `run_id`, `run_dir` (как в `_build_payload` из `agent_tool.py`).
Валидация: контракт зафиксирован в [../../../tool_contract.md](../../../tool_contract.md)
и покрыт `tests/test_serialize.py` — сверяться с ним, не выдумывать поля.

### 5.3. `task_manager.py`

Состояния: `submitted` → `working` → `completed` | `failed` | `canceled`.
(`input_required` из первой редакции документов — не реализуем: агент
не задаёт уточняющих вопросов; зафиксировано в
[../../deferred/a2a_refactor_deferred.md](../../deferred/a2a_refactor_deferred.md).)

Требования:

- задачи исполняются в пуле потоков, лимит — `max_concurrent_tasks`,
  превышение → задача в очереди со статусом `submitted`;
- **`start_run()` вызывается внутри рабочего потока**, иначе `ContextVar`
  с `RunContext` не долетит (см. шаг 04) и дедлайн/стоп будут не тем прогоном;
- прогресс: `progress_callback(done, total, message)` из `runtime` →
  `TaskStatusUpdateEvent`; интервал не чаще `PROGRESS_INTERVAL_SEC`;
- отмена: `tasks/cancel` → `stop_run()` **этой** задачи (не глобальный);
- TTL: завершённые задачи вычищаются через `task_ttl_sec`;
- дедлайн: как в текущем `server.py` — **не** `asyncio.wait_for`. Поток
  не убивать; агент сам увидит `is_deadline_reached()` и вернёт
  `status="partial"` через `_finalize()`. Это поведение P0.2, ломать нельзя.

### 5.4. `executor.py`

Мост между A2A-задачей и агентом:

```python
def execute(inp: RunPipelineInput, emit) -> dict:
    """Запускает BlocksNetAgent и отдаёт тот же payload, что MCP-tool.

    emit(status, message, artifacts) — колбэк прогресса в task_manager.
    """
```

Переиспользовать `_build_payload()` из `blocksnet_mcp/agent_tool.py` —
не копировать: один формат ответа для A2A и MCP. Если импорт из
`blocksnet_mcp` в `blocksnet_agent` кажется неправильным направлением
зависимости — вынести `_build_payload` и `to_json` в общий модуль
(`blocksnet_agent/payload.py`), а `agent_tool.py` переключить на него.
**Второй копии функции быть не должно.**

### 5.5. `skills/run_pipeline.py` и `skills/analyze_urban_question.py`

- `run_pipeline` — создаёт задачу, стримит статусы, отдаёт артефакты.
- `analyze_urban_question` — вызывает `run_pipeline` и **блокирующе** ждёт
  терминального статуса, отдаёт финальный JSON. Никакой второй реализации
  pipeline (см. Q2).

Артефакты: файлы из `RunLogger.saved_files` (карты, CSV) объявлять как A2A
artifacts с путями; содержимое не инлайнить.

### 5.6. `agent_card.py`

Поля: `name`, `description`, `version` (взять из версии пакета),
`url` (`public_url` или `http://host:port`), `defaultInputModes`/
`defaultOutputModes` (`text`, `application/json`), `capabilities.streaming=true`,
`pushNotifications=false` (не реализуем, см. 09), `skills` — два, с
`id`/`name`/`description`/`tags`/`examples`.

Точные имена полей — по версии SDK из `spike-a2a.md`.

### 5.7. `server.py` + `__main__.py` + `blocksnet_agent/__main__.py`

- `server.py`: сборка приложения, регистрация executor, `main()` с uvicorn.
- `/health` — простой liveness (понадобится в compose, шаг 07).
- `blocksnet_agent/__main__.py` — прокси на `a2a.server.main` (задача 4.3).

### 5.8. `scripts/smoke_a2a_agent.py`

Сценарий: старт сервера → `GET` Agent Card → `analyze_urban_question`
с коротким вопросом → проверка обязательных полей ответа → `run_pipeline`
с проверкой, что пришло ≥2 статусных события. Требует LLM-конфига;
без него — явное сообщение, не трейсбек.

---

## Тесты

Без сети и без реального LLM: `BlocksNetAgent.run` подменяется monkeypatch'ем
(образец — `tests/test_async_mcp_contract.py`).

`tests/test_a2a_card.py`
- карточка валидируется моделью SDK;
- ровно два skill, id совпадают с реестром `skills/__init__.py`;
- `url` отражает `A2A_PUBLIC_URL`, если задан.

`tests/test_a2a_skills.py`
- `analyze_urban_question` возвращает те же ключи, что MCP-tool сегодня
  (сверка с `test_tool_contract.py` / `test_serialize.py`);
- `run_pipeline` эмитит `submitted` → `working` → `completed`;
- ошибка агента → `failed` + `error_code`, не исключение наружу;
- пустой `question` → `VALIDATION_ERROR` (тот же код, что в MCP).

`tests/test_a2a_tasks.py`
- лимит конкурентности соблюдается;
- `cancel` останавливает **только** свою задачу (интеграция с шагом 04);
- дедлайн даёт `partial`, а не `failed`;
- задачи вычищаются по TTL.

---

## DoD

- [ ] `python -m blocksnet_agent` поднимает сервер на `A2A_PORT`
- [ ] `curl <путь из spike-a2a.md>` отдаёт валидный Agent Card
- [ ] `python -m pytest tests/test_a2a_*.py -q` — зелёный
- [ ] `python -m pytest -q` — не хуже baseline
- [ ] `scripts/smoke_a2a_agent.py` проходит с реальным LLM-конфигом
- [ ] Ответ `analyze_urban_question` (A2A) идентичен по набору ключей
      ответу MCP-tool — проверено тестом, не глазами
- [ ] `git diff --stat blocksnet_agent/agent.py` — пусто
- [ ] Коммит `a2a/05: A2A service with agent card and two skills`

## Не делать

- Не вызывать MCP из агента.
- Не реализовывать `input_required` и push notifications.
- Не менять формат выходного JSON — он в контракте и в тестах.
- Не заменять обработку дедлайна на `asyncio.wait_for` (убьёт поток до
  финализации и вместо `partial` получится `failed`).
- Не запускать реальный LLM в тестах.

## Откат

Пакет `blocksnet_agent/a2a/` изолирован — удаление папки, `__main__.py`
и тестов возвращает репозиторий к состоянию после шага 04. Общий
`payload.py` (задача 5.4), если он был выделен, оставить: он полезен сам
по себе и не ломает MCP.
