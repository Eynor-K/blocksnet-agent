# Шаг 03 — MCP-server: 32 raw tool, без обязательного LLM

**Цель.** `python -m blocksnet_mcp` поднимает все инструменты каталога,
стартует без `CHAT_URL`/`API_KEY`, ничего из существующего не ломает.

**Предусловия.** Шаги 01 и 02 завершены.

**Оценка.** 1.5 дня. Самый крупный шаг ветки MCP.

---

## Задачи

### 3.1. `blocksnet_mcp/envelope.py` — конверт ответа

Формат зафиксирован в [../../decisions/open_questions.md](../../decisions/open_questions.md) Q5:

```python
def build_envelope(
    tool: str,
    session_id: str,
    text: str,
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    """{'status','tool','session_id','text','artifacts','error_code'}"""
```

- `status`/`error_code` определяются по тексту. **Переиспользовать
  существующую классификацию**, не писать свою: `FAILURE_MARKERS` из
  `blocksnet_agent.metrics` и логику `_failed_observation` из
  `blocksnet_agent/tools/__init__.py`. Если функция приватная — вынести её
  в `catalog.py` как публичную `is_failed_observation(text)` и переиспользовать
  в обоих местах (правка `tools/__init__.py` допустима, поведение не меняется).
- `text` отдаётся **как есть**, без переформатирования (инвариант 4).
- Коды ошибок: `TOOL_FAILED` (инструмент вернул текст-ошибку),
  `TOOL_EXCEPTION` (исключение), `SESSION_NOT_FOUND`, `DEADLINE_EXCEEDED`,
  `VALIDATION_ERROR` — согласовать с уже используемыми в `tools_mcp.py`
  (`VALIDATION_ERROR`, `AGENT_EXCEPTION`), не плодить синонимы.

### 3.2. Переработка `blocksnet_mcp/settings.py`

Убрать из **обязательных** LLM-поля:

```python
# было: chat_url: str = Field(validation_alias="CHAT_URL")   # required!
chat_url: str | None = Field(default=None, validation_alias="CHAT_URL")
api_key: str | None = Field(default=None, validation_alias="API_KEY")
model: str | None = Field(default=None, validation_alias="MODEL")
```

Добавить: `session_ttl_sec`, `max_sessions` (шаг 02),
`enable_agent_tool: bool = Field(default=True, validation_alias="ENABLE_AGENT_TOOL")`.

Оставить: `data_dir`, `output_dir`, `deadline_sec`, `progress_interval_sec`,
`max_iterations`, `model_post_init` (нормализация путей).

Это ключевая цель шага: сегодня отсутствие `CHAT_URL` роняет **импорт**
настроек, то есть весь сервер.

### 3.3. `blocksnet_mcp/agent_tool.py` — переезд `tools_mcp.py`

- `git mv blocksnet_mcp/tools_mcp.py blocksnet_mcp/agent_tool.py`.
- Оставить `blocksnet_mcp/tools_mcp.py` как shim: `from blocksnet_mcp.agent_tool import *`
  плюс `# DEPRECATED: см. docs/a2a_refactor` — тесты и примеры импортируют
  его напрямую.
- **Ленивые импорты LLM**: `from blocksnet_agent import BlocksNetAgent` и
  `AgentSettings` перенести внутрь `analyze_urban_question()`. Сейчас они на
  уровне модуля (строки 8–10) — при импорте пакета тянут весь агент.
- В начале вызова — явная проверка настроек с понятной ошибкой:
  ```python
  if not (settings.chat_url and settings.api_key):
      return {"status": "failed", "error_code": "LLM_NOT_CONFIGURED",
              "error": "analyze_urban_question требует CHAT_URL и API_KEY"}
  ```
- Docstring начать с `[DEPRECATED] Используйте A2A skill run_pipeline. ...`

### 3.4. `blocksnet_mcp/server.py` — динамическая регистрация

```python
mcp = FastMCP("blocksnet")

def _register_catalog_tools(mcp: FastMCP) -> None:
    """Регистрирует инструменты каталога, каждый — с session_id в сигнатуре."""
```

Ключевые требования:

1. **`session_id` инжектится в сигнатуру** каждого инструмента как
   необязательный `session_id: str = "default"`. FastMCP выводит схему из
   сигнатуры, поэтому обёртку строить через `functools.wraps` + явную
   правку `__signature__` (`inspect.Signature`), либо генерировать модель
   аргументов из `spec.args_schema` и добавлять поле. Проверить, что
   `tools/list` показывает `session_id` в схеме входа.
2. **Каталог строится per-session, не глобально.** На каждый вызов:
   ```python
   session = get_session_store().get_or_create(session_id)
   specs = build_catalog(session.state, settings.data_dir, settings.output_dir)
   tool = get_spec(specs, name).tool
   ```
   Построение каталога дешёвое (создание замыканий), данные не перечитываются —
   они лежат в `session.state`. Регистрация же в FastMCP делается один раз,
   при старте, по каталогу над временным пустым `state` — оттуда берутся
   только имена, описания и схемы.
3. **Дедлайн на вызов**: обернуть в `start_run(deadline_sec=...)` из
   `blocksnet_agent.runtime` — инструменты внутри проверяют
   `is_deadline_reached()`. Без этого долгий `compute_scenario_provision`
   зависнет без ограничения.
4. **Исключения не пробрасывать**: любое → `envelope` со `status="failed"`,
   `error_code="TOOL_EXCEPTION"`. MCP-клиент должен получать структуру, а не
   транспортную ошибку (это уже принцип P0.2 в текущем сервере).
5. **Артефакты**: после вызова собрать новые файлы из `RunLogger`
   (`blocksnet_agent.runtime.get_run_logger().saved_files`) и положить пути
   в `artifacts`.

### 3.5. Служебные MCP-инструменты

`open_session()`, `close_session(session_id)`, `session_info(session_id=None)` —
тонкие обёртки над `SessionStore`. В каталог инструментов агента **не**
добавляются: они существуют только на уровне MCP.

### 3.6. `blocksnet_mcp/__main__.py`

```python
from blocksnet_mcp.server import main

if __name__ == "__main__":
    main()
```

Сегодня `python -m blocksnet_mcp` не работает — файла нет.

### 3.7. Обратная совместимость (6 мест из шага 00.4)

| Место | Что сделать |
|---|---|
| `blocksnet_mcp/__init__.py` | реэкспорт `analyze_urban_question` **лениво**, через `__getattr__` (образец — `blocksnet_agent/__init__.py`), чтобы импорт пакета не тянул агента |
| `tests/test_tool_contract.py` | не трогать — должен пройти как есть |
| `tests/test_async_mcp_contract.py` | не трогать |
| `scripts/smoke_client.py` | не трогать; добавить флаг `--raw-tools` для нового пути |
| `examples/_lib/run_mcp.py` | не трогать |
| `examples/city_picker.py` | не трогать |

Если какой-то из тестов краснеет — это дефект шага, а не устаревший тест
(инвариант 6).

### 3.8. `scripts/smoke_mcp_tools.py`

Поднимает сервер по stdio (`mcp.client.stdio`) и проверяет сценарий:

```
tools/list                                    → каталог, в нём есть session_id
open_session                                  → sid
load_blocks(session_id=sid)                   → status ok
list_cached_data(session_id=sid)              → в тексте фигурируют blocks
list_cached_data(session_id="other")          → кэш пуст (изоляция!)
compute_service_provision("school", sid)      → status ok
get_analysis_results(<result_key>, sid)       → находит результат
close_session(sid)                            → ok
```

Печатает таблицу «инструмент → статус → длина текста», код возврата ≠ 0
при любом `failed`. Требует реальных данных в `DATA_DIR` — если их нет,
скрипт должен явно сказать об этом, а не падать трейсбеком.

---

## Тесты — `tests/test_mcp_tool_exposure.py`

```python
def test_all_catalog_tools_are_registered():
    """Экспозиция MCP == каталог + служебные. Число не хардкодим."""
    exposed = {t.name for t in mcp_registered_tools()}
    expected = {s.name for s in build_catalog({}, ..., ...)}
    assert expected <= exposed

def test_submit_answer_not_exposed():
    assert "submit_answer" not in {t.name for t in mcp_registered_tools()}

def test_every_tool_has_session_id_in_input_schema():
    for t in mcp_registered_tools():
        if t.name in {"open_session"}: continue
        assert "session_id" in t.inputSchema["properties"]

def test_server_imports_without_llm_env(monkeypatch):
    """Главная цель шага: без CHAT_URL/API_KEY сервер поднимается."""
    monkeypatch.delenv("CHAT_URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    importlib.reload(blocksnet_mcp.settings)
    importlib.reload(blocksnet_mcp.server)   # не должно бросить

def test_agent_tool_reports_llm_not_configured(monkeypatch):
    monkeypatch.delenv("CHAT_URL", raising=False)
    result = analyze_urban_question("вопрос")
    assert result["error_code"] == "LLM_NOT_CONFIGURED"

def test_agent_tool_hidden_when_flag_off(monkeypatch): ...

def test_envelope_marks_failure_text_as_failed():
    env = build_envelope("load_blocks", "default", "Ошибка при загрузке кварталов: нет файла")
    assert env["status"] == "failed" and env["error_code"] == "TOOL_FAILED"

def test_tool_exception_becomes_envelope(): ...
```

Тесты не должны требовать реальных данных: инструменты возвращают
текст-ошибку при отсутствии файлов — это валидный `failed`-конверт.

---

## DoD

- [ ] `CHAT_URL= API_KEY= python -m blocksnet_mcp` — стартует
- [ ] `python -m pytest tests/test_mcp_tool_exposure.py -q` — зелёный
- [ ] `python -m pytest -q` — **не хуже baseline**; `test_tool_contract.py`
      и `test_async_mcp_contract.py` зелёные без единой правки
- [ ] `scripts/smoke_mcp_tools.py` проходит на реальных данных (или явно
      сообщает об их отсутствии)
- [ ] Изоляция сессий подтверждена вручную: `list_cached_data` в чужой
      сессии показывает пустой кэш
- [ ] `blocksnet_agent/` не изменён, кроме возможного выноса
      `is_failed_observation` (задача 3.1)
- [ ] Коммит `a2a/03: MCP exposes raw tools with sessions, no LLM required`

## Не делать

- Не удалять `analyze_urban_question` (Q7) и не менять его контракт.
- Не менять текст, который возвращают инструменты.
- Не строить каталог один раз глобально и не переиспользовать `state`
  между сессиями.
- Не добавлять `submit_answer`, `open_session` и прочие MCP-специфичные
  инструменты в набор агента.
- Не заводить свою классификацию ошибок параллельно `FAILURE_MARKERS`.

## Откат

Шаг крупный, поэтому коммиты дробить по задачам (3.1–3.8), чтобы можно было
откатить регистрацию, сохранив envelope и settings. Полный откат:
`git revert` коммитов шага; `tools_mcp.py` вернуть через `git mv` обратно.
