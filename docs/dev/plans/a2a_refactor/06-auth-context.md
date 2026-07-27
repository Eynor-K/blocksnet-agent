# Шаг 06 — Auth и контекст сценария (MAS)

**Цель.** Оба сервиса принимают Bearer и умеют работать в контексте
`scenario_id`/`project_id`.

**Предусловия.** Шаги 03 и 05 завершены (обе ветки сошлись).

**Оценка.** 1 день.

**Связь:** это этапы 1–4 из [../mas_integration.md](../mas_integration.md),
распределённые по двум сервисам. Сверяться с тем документом по кодам ошибок
и формату токена — он источник истины по MAS-контракту.

---

## Задачи

### 6.1. Auth: `blocksnet_agent/a2a/auth.py` и `blocksnet_mcp/auth.py`

Одинаковая логика, две точки применения. Чтобы не дублировать —
реализация в одном месте (предложение: `blocksnet_agent/authcore.py`,
без зависимостей от A2A/MCP), в сервисах — тонкие адаптеры под транспорт.

- `AUTH_ENABLED` (default `false` — локальная разработка не должна ломаться).
- Bearer-токен: сверка с `MAS_BEARER_TOKEN` (константное время сравнения —
  `hmac.compare_digest`).
- JWT — задел на прод: интерфейс `verify(token) -> Principal | None`,
  реализация `StaticTokenVerifier` сейчас, `JWTVerifier` позже.
- Коды: `401` — токена нет/невалиден, `403` — токен валиден, но доступ к
  `scenario_id` не разрешён.
- **Ошибки не должны раскрывать детали**: одинаковый текст для «нет токена»
  и «неверный токен».
- Для MCP по stdio auth не применяется (транспорт локальный) — включается
  только на HTTP-транспорте; это должно быть явно в коде, а не «само собой».

### 6.2. Контекст сценария

`blocksnet_agent/a2a/context.py` и `blocksnet_mcp/context.py`:

```python
@dataclass(frozen=True)
class ScenarioContext:
    scenario_id: str | None
    project_id: str | None
    data_dir: Path        # разрешённый каталог данных
    output_dir: Path
```

- `resolve_context(scenario_id, project_id, settings) -> ScenarioContext`.
- Без `scenario_id` → дефолтные `DATA_DIR`/`OUTPUT_DIR` (текущее поведение
  сохраняется полностью).
- С `scenario_id` → `DATA_DIR/<scenario_id>/`; если каталога нет —
  материализация из UrbanDB (`URBANDB_URL`, `URBANDB_TOKEN`), при
  недоступности — `SCENARIO_NOT_MATERIALIZED`, а не падение.
- Кэш материализации на диске + отметка времени; повторный запрос не
  перекачивает данные.
- **Валидация пути обязательна**: `scenario_id` приходит извне и попадает в
  путь. Разрешить только `[a-zA-Z0-9_-]{1,64}`, результат проверить через
  `Path.resolve().is_relative_to(DATA_DIR.resolve())`. Без этого — обход
  каталога.

### 6.3. Связка сессий и сценариев в MCP

`session.meta["scenario_id"]` заполняется при `open_session(scenario_id=...)`;
`data_dir`/`output_dir` сессии берутся из `ScenarioContext`. Инструменты
уже получают `data_dir` из фабрики — менять их не нужно, достаточно
строить каталог с путями сессии (шаг 03, задача 3.4).

Ограничение: сессия привязана к одному сценарию. Смена `scenario_id` в
существующей сессии → `SESSION_SCENARIO_MISMATCH`, клиент открывает новую.

### 6.4. Прокидывание в A2A

`RunPipelineInput.scenario_id`/`project_id` → `ScenarioContext` →
`AgentSettings(data_dir=..., output_dir=...)` для конкретного прогона.
Глобальный `get_settings()` (он `lru_cache`) для этого **не** годится —
настройки прогона передаются явно.

---

## Тесты

`tests/test_auth.py`
- `AUTH_ENABLED=false` → доступ без токена;
- `true` + нет токена → 401; неверный → 401; верный → 200;
- сообщения об ошибке для «нет» и «неверный» совпадают;
- stdio-MCP не требует токена даже при `AUTH_ENABLED=true`.

`tests/test_context_adapter.py`
- без `scenario_id` → дефолтные каталоги (поведение не изменилось);
- с `scenario_id` → подкаталог;
- `scenario_id="../../etc"` → `VALIDATION_ERROR`, файловая система не тронута;
- `scenario_id="a/b"`, `"a\x00b"`, пустая строка → отклонены;
- UrbanDB недоступна → `SCENARIO_NOT_MATERIALIZED` (мок HTTP, без сети);
- повторный вызов не перекачивает (мок считает обращения).

`tests/test_mcp_session_scenario.py`
- смена сценария в существующей сессии → `SESSION_SCENARIO_MISMATCH`.

---

## DoD

- [ ] `python -m pytest tests/test_auth.py tests/test_context_adapter.py -q` — зелёный
- [ ] Path-traversal тесты присутствуют и зелёные (это не опция)
- [ ] `AUTH_ENABLED` не задан → всё работает как раньше
- [ ] `python -m pytest -q` — не хуже baseline
- [ ] Коды ошибок сверены с `mas_integration_implementation_plan.md`
- [ ] Коммит `a2a/06: bearer auth and scenario context for both services`

## Не делать

- Не включать `AUTH_ENABLED=true` по умолчанию — сломает локальную работу
  и примеры.
- Не подставлять `scenario_id` в путь без валидации и `resolve()`-проверки.
- Не логировать токены и заголовок `Authorization` (в том числе в
  `outputs/mcp_trace.log`, куда пишет `_trace`).
- Не тянуть реальную UrbanDB в тесты.

## Откат

Модули изолированы; при `AUTH_ENABLED=false` и отсутствии `scenario_id`
код-пути не активируются, поэтому откат безопасен на любом этапе.
