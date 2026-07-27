# A2A-рефакторинг: отчёт о завершении

**Дата:** 2026-07-22
**Ветка:** `feat/a2a-refactor`
**План:** `docs/a2a_refactor/implementation/` (9 шагов, 00–08)
**Статус:** ✅ Все шаги завершены. Готов к приёмке.

---

## 1. Что сделано по шагам

| Шаг | Название | Commit | Ключевые результаты |
|---|---|---|---|
| 00 | Preflight | `fdfa4e5` | env (.venv-spike), baseline (89 passed), a2a-sdk 1.1.1 spike, pyproject extras |
| 01 | Tool catalog | `a7f4f82` | `build_catalog()` (32 tool-spec), `TOOL_BLOCKLIST` (submit_answer) |
| 02 | Session store | `652c063` | `SessionStore` (LRU+TTL+изоляция) |
| 03 | MCP server | `613c7b9` | 32 raw-tools через `mcp.add_tool()`, lazy singleton, **MCP без LLM** |
| 04 | Agent decoupling | `59952f0` | per-run stop_event, settings inheritance prep |
| 05 | A2A service | `1277c0c` | FastAPI + Agent Card + 2 skill-а (`run_pipeline`, `analyze_urban_question`) |
| 06 | Auth + context | `e5799fc` | `authcore.py` + `context.py`, A2A middleware, MCP session scenario binding |
| 07 | Docker | `24f816a` | multi-stage, 2 образа, compose, healthcheck |
| 08 | Docs | (этот коммит) | catalog generator, contract v2, A2A Agent Card, единая env-таблица |

## 2. Фактические числа

### Тесты

| Этап | Значение |
|---|---|
| Baseline (до a2a) | 89 passed |
| После шага 08 | **257 passed** (+168) |
| Регрессий | 0 |

**Распределение новых тестов:**
- `test_tool_catalog.py` (12) — каталог
- `test_mcp_session.py` (25) — сессии
- `test_mcp_tool_exposure.py` (20) — MCP-экспозиция
- `test_runtime_stop_scope.py` (12) — per-run stop
- `test_settings_inheritance.py` (6) — settings
- `test_a2a_card.py` (10) — Agent Card
- `test_a2a_tasks.py` (15) — task_manager
- `test_a2a_skills.py` (9) — skills
- `test_auth.py` (19) — auth
- `test_context_adapter.py` (20) — context
- `test_mcp_session_scenario.py` (8) — session+scenario
- `test_image_deps.py` (7) — разделение deps
- `test_tool_catalog_docs.py` (5) — каталог актуален

### Код

| Метрика | Значение |
|---|---|
| Новых файлов | 24 (включая тесты и Docker) |
| Новых строк кода | ~3500 (код + тесты + docs) |
| `agent.py` правок | **0** (инвариант 1 соблюдён) |
| `hypotheses.py` правок | **0** |
| `metrics.py` правок | **0** |
| `registry.py` правок | **0** |
| `catalog.py` правок | +127 (новый файл, шаг 01) |

### MCP-каталог

- **32 доменных инструмента** + **3 служебных** (`open_session`, `close_session`, `session_info`)
- **`submit_answer`** заблокирован через `TOOL_BLOCKLIST`
- Каталог auto-generated (`scripts/generate_tool_catalog.py` → `docs/mcp_tool_catalog.md`, 731 строка, 38 KB)

### A2A Agent Card

- 2 skill-а: `run_pipeline` (основной), `analyze_urban_question` (DEPRECATED, back-compat)
- a2a-sdk 1.1.1, protobuf-карточка с `supportedInterfaces`
- Тест `test_a2a_card.py::test_card_matches_real_skills` — реальная карточка

### Docker

- `Dockerfile.mcp` — multi-stage, **без LLM-зависимостей** (verified: `import blocksnet_mcp.server` в subprocess → CLEAN)
- `Dockerfile.agent` — с `langgraph`/`langchain_openai`/`tiktoken`/`a2a-sdk`, healthcheck на `/health`
- `docker-compose.yml` — общий volume `./data`/`./outputs`, mem_limit agent=4g, mcp=2g

## 3. Отклонения от плана

| Шаг | Отклонение | Причина |
|---|---|---|
| 01 | `tools/__init__.py:make_tools()` получил kw-only `registry_out: dict \| None = None` (не через двойной вызов) | Альтернатива из плана B плодила бы два источника истины |
| 03 | `server.py`: `mcp = _build_server()` стал lazy singleton через `get_mcp()` | Иначе `import blocksnet_mcp.server` тянет `blocksnet_agent` → нарушает разделение зависимостей MCP-образа |
| 03 | `envelope.py`: локальная копия `is_failed_observation` (без импорта `blocksnet_agent`) | То же — для MCP-образа |
| 03 | `serialize.py`: `AgentResult` через `TYPE_CHECKING` | То же |
| 05 | Skills объединены в один файл `blocksnet_agent/a2a/skills.py` (вместо подпакета `skills/`) | 2 skill-а по ~50 строк каждый — отдельная папка избыточна |
| 06 | `MAS_BEARER_TOKEN` в `MCPSettings` через `AUTH_ENABLED`/`MAS_BEARER_TOKEN` (не `MCP_BEARER_TOKEN`) | Согласуется с `A2A_MAS_BEARER_TOKEN` |

Все отклонения — косметические (именование) или усиления инвариантов. Функционально план выполнен полностью.

## 4. Что осталось (deferred)

См. `docs/dev/deferred/a2a_refactor_deferred.md` (что осталось после рефакторинга)
и `docs/dev/README.md` (индекс всех dev-материалов).

1. **Реальный LLM-прогон через A2A** — требует настроенный `.env` с `CHAT_URL`/`API_KEY` (текущая песочница — без реального LLM).
2. **Real UrbanDB integration** — `materializer` в `blocksnet_agent/context.py` сейчас in-process factory; для MAS-этапа 4 нужен HTTP-клиент к Urban API.
3. **JWT-валидатор** — `TokenVerifier` Protocol позволяет подменить, но конкретный JWT-имплементер не написан (текущий `StaticTokenVerifier` — для dev и smoke).
4. **Push-уведомления в Agent Card** — `capabilities.pushNotifications=false` (задел для v2.1).
5. **Архивация `docs/a2a_refactor/`** — после приёмки Игорем.

## 5. Как приёмка

### Smoke-проверки (уже зелёные)

```bash
# MCP без LLM
CHAT_URL= API_KEY= python -c "import blocksnet_mcp.server; print('OK')"

# Разделение зависимостей
pytest tests/test_image_deps.py -v  # 7 passed

# Каталог актуален
pytest tests/test_tool_catalog_docs.py -v  # 5 passed

# Agent Card реальный
python scripts/smoke_a2a_agent.py  # SMOKE OK
python scripts/smoke_mcp_tools.py  # SMOKE OK

# Полный pytest
pytest  # 257 passed, 0 regressions
```

### Docker (требует docker)

```bash
docker compose build
bash scripts/smoke_docker.sh  # требует docker + curl
```

## 6. Заключение

Цели a2a-рефакторинга достигнуты:

- ✅ **MCP-server без LLM** — главная архитектурная развязка; `import blocksnet_mcp.server` НЕ тянет `langgraph`/`tiktoken` (verified).
- ✅ **A2A-агент с двумя skill-ами** — Agent Card, JSON-RPC `/`, healthcheck, lifecycle через `TaskManager`.
- ✅ **Auth + scenario_id** — Bearer с constant-time compare, anti-enumeration, path-traversal защита.
- ✅ **Per-run stop** — cancel одной задачи не валит соседние (concurrent-safety).
- ✅ **Docker** — два образа (mcp без LLM, agent с LLM), compose с healthcheck'ами.
- ✅ **Документация** — catalog (auto-generated), контракт, A2A Agent Card, env-таблица.

**Следующие шаги — на усмотрение Игоря:**
1. Приёмка (rebase в main или merge).
2. Архивация `docs/a2a_refactor/` → `docs/archive/a2a_refactor/`.
3. Переход к MAS-этапам 7-10 (registry, e2e, hardening, handoff).