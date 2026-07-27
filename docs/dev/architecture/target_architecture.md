# Целевая архитектура: A2A-сервис + MCP raw tools

Целевая картина после рефакторинга. Мотивация — [reasoning.md](../decisions/reasoning.md),
принятые решения — [open_questions.md](../decisions/open_questions.md), исполнение —
[implementation/](implementation/).

Ред. 2026-07-21: приведено в соответствие с фактическим кодом
(см. [review.md](../decisions/review.md)). Ключевое отличие от первой редакции —
**агент не вызывает MCP**; оба сервиса равноправно используют общую фабрику
инструментов (Q6).

## 1. Целевая диаграмма

```text
┌──────────────────────────────────────────────────────────────────────┐
│                       MAS / внешние клиенты                          │
│   Hermes, свой A2A-клиент            Claude Desktop, Cursor, CI      │
└───────────────┬──────────────────────────────────┬───────────────────┘
                │ A2A JSON-RPC (HTTP)              │ MCP (stdio → HTTP)
                ▼                                  ▼
┌───────────────────────────────────┐  ┌───────────────────────────────────┐
│ blocksnet-agent-service           │  │ blocksnet-mcp                     │
│ (пакет blocksnet_agent.a2a)       │  │ (пакет blocksnet_mcp)             │
│                                   │  │                                   │
│ ┌───────────────────────────────┐ │  │ ┌───────────────────────────────┐ │
│ │ Agent Card                    │ │  │ │ tools/list  (32 инструмента)  │ │
│ │ /.well-known/agent-card.json  │ │  │ │  load_blocks                  │ │
│ │  skills:                      │ │  │ │  load_accessibility_matrix    │ │
│ │   • run_pipeline              │ │  │ │  list_cached_data             │ │
│ │   • analyze_urban_question    │ │  │ │  list_service_types           │ │
│ │  capabilities:                │ │  │ │  list_key_services            │ │
│ │   • streaming                 │ │  │ │  get_block_info               │ │
│ └───────────────────────────────┘ │  │ │  get_metric_for_block         │ │
│ ┌───────────────────────────────┐ │  │ │  get_weakest_services         │ │
│ │ skills/  (одна реализация,    │ │  │ │  get_analysis_results         │ │
│ │  два режима ожидания)         │ │  │ │  compute_* (network/services/ │ │
│ └───────────────────────────────┘ │  │ │            indicators/prov.)  │ │
│ ┌───────────────────────────────┐ │  │ │  suggest_target_blocks        │ │
│ │ task_manager                  │ │  │ │  propose_zone_development     │ │
│ │  submitted → working →        │ │  │ │  compute_scenario_provision   │ │
│ │  completed / failed /         │ │  │ │  render_metric_map            │ │
│ │  input_required               │ │  │ │  find_tools / get_tool_help   │ │
│ └───────────────────────────────┘ │  │ │  + open/close/info session    │ │
│ ┌───────────────────────────────┐ │  │ └───────────────────────────────┘ │
│ │ BlocksNetAgent — БЕЗ ИЗМЕНЕНИЙ│ │  │ ┌───────────────────────────────┐ │
│ │  PTR-цикл · RAG · инварианты  │ │  │ │ SessionStore                  │ │
│ │  hypotheses · metrics ·       │ │  │ │  session_id → {state,         │ │
│ │  submit_answer · state        │ │  │ │   data_dir, output_dir}       │ │
│ └───────────────────────────────┘ │  │ │  TTL + LRU                    │ │
│ ┌───────────────────────────────┐ │  │ └───────────────────────────────┘ │
│ │ A2ASettings(Settings)         │ │  │ ┌───────────────────────────────┐ │
│ │  CHAT_URL · API_KEY · MODEL   │ │  │ │ agent_tool.py  [DEPRECATED]   │ │
│ │  + PORT · AUTH_* · MAS_*      │ │  │ │  analyze_urban_question       │ │
│ └───────────────────────────────┘ │  │ │  ENABLE_AGENT_TOOL, LLM —     │ │
│ ┌───────────────────────────────┐ │  │ │  импорт ЛЕНИВЫЙ               │ │
│ │ auth · context (scenario_id)  │ │  │ └───────────────────────────────┘ │
│ └───────────────────────────────┘ │  │ ┌───────────────────────────────┐ │
│                                   │  │ │ MCPSettings — без CHAT_URL/   │ │
│                                   │  │ │ API_KEY/MODEL как required    │ │
│                                   │  │ │ auth · context (scenario_id)  │ │
└─────────────────┬─────────────────┘  └─────────────────┬─────────────────┘
                  │                                      │
                  └──── blocksnet_agent.tools.catalog ────┘
                       build_catalog() / make_tools(state, dirs)
                       у каждого процесса — свой state
                                     │
                                     ▼
                       blocksnet (расчёты) + DATA_DIR
```

## 2. Принципы

### 2.1. Агент знает pipeline, MCP — нет

| Слой | PTR-цикл | Гипотезы / инварианты | LLM | RAG по tools |
|---|---|---|---|---|
| **A2A-сервис** | да | да | да | да |
| **MCP-сервер** | нет | нет | нет | да — `find_tools`/`get_tool_help` детерминированы (keyword-поиск, без эмбеддингов) |
| **blocksnet lib** | нет | нет | нет | нет |

Единственное место, где MCP касается LLM — deprecated `agent_tool.py`, и то
лениво: без `ENABLE_AGENT_TOOL=false` сервер всё равно стартует без
`CHAT_URL`/`API_KEY`, потому что импорт агента происходит внутри вызова.

### 2.2. Что общее, что раздельное

| Компонент | A2A-сервис | MCP-сервер |
|---|---|---|
| `blocksnet_agent/tools/*` | общий код | общий код |
| `make_tools()` / `catalog.py` | общий вызов | общий вызов |
| экземпляр `state` | свой (per-run) | свой (per-session) |
| `serialize.py` | используется | используется agent_tool'ом |
| `runtime.py` (RunContext, дедлайны) | используется | используется для дедлайна вызова |
| LLM (`llm.py`, `prompts.py`) | да | нет |
| `hypotheses.py`, `metrics.py` | да | нет |

### 2.3. Потоки данных

| Поток | Откуда | Куда | Транспорт |
|---|---|---|---|
| Запрос пользователя | MAS / A2A-клиент | A2A-сервис | A2A JSON-RPC / HTTP |
| Прогресс, артефакты | A2A-сервис | клиент | `TaskStatusUpdateEvent` / artifacts |
| Вызов инструмента (агент) | PTR-цикл | tools | **in-process**, общий `state` |
| Вызов инструмента (внешний) | MCP-клиент | tools | MCP, `state` сессии |
| Данные сценария | UrbanDB | context adapter | HTTP → материализация в `DATA_DIR` |
| Артефакты расчётов | tools | `OUTPUT_DIR` | файлы, пути в конверте ответа |

### 2.4. Контракты

| Контракт | Файл | Статус |
|---|---|---|
| A2A Agent Card | `docs/a2a_agent_card.md` | новый |
| A2A skill `run_pipeline` | `docs/tool_contract.md` | новый |
| A2A skill `analyze_urban_question` | `docs/tool_contract.md` | тот же JSON, что сейчас |
| MCP tool catalog (32) | `docs/mcp_tool_catalog.md` | генерируется скриптом |
| MCP конверт ответа | `docs/tool_contract.md` | `{status, tool, session_id, text, artifacts, error_code}` |
| MCP сессии | `docs/tool_contract.md` | `session_id`, TTL, `open/close/info` |
| MAS auth | `docs/deployment.md` | Bearer/JWT, 401/403 |

### 2.5. Модель сессий MCP

Инструменты замкнуты над мутабельным `state` — без сессии половина каталога
неработоспособна (см. [open_questions.md](../decisions/open_questions.md), Q4).

```text
open_session()                       → {"session_id": "s-7f3a"}
load_blocks(session_id="s-7f3a")     → state["blocks"]        (в этой сессии)
compute_service_provision(           → state["provision_school"]
    "school", session_id="s-7f3a")
get_analysis_results(                → читает state["provision_school"]
    "provision_school", session_id="s-7f3a")
close_session("s-7f3a")              → память освобождена
```

- `session_id` необязателен: по умолчанию `"default"` — однопользовательский
  сценарий (Claude Desktop, CI) работает без изменений на стороне клиента.
- Фактический `session_id` всегда возвращается в конверте.
- Ограничения: TTL `SESSION_TTL_SEC` (1800 с), LRU `MAX_SESSIONS` (8),
  вытеснение по обращению. Стор — в памяти процесса; горизонтальное
  масштабирование требует sticky-сессий (отложено).

### 2.6. Независимое развитие

```text
новый tool = blocksnet_agent/tools/<mod>.py + регистрация в фабрике
           → агент видит через RAG-описание (registry.py)
           → MCP экспонирует автоматически (catalog.py)
           → контрактный тест сверяет обе экспозиции

новый A2A-skill = blocksnet_agent/a2a/skills/<name>.py + Agent Card
                → MCP не затронут

новая LLM-модель = CHAT_URL/MODEL в .env
                 → перезапуск только A2A-сервиса
```

## 3. Структура репозитория после рефакторинга

`←` помечено новое, `~` — изменяемое, остальное без изменений.

```text
blocksnet-mcp/
├── blocksnet_agent/
│   ├── agent.py                     # ядро PTR/RAG/инварианты — НЕ ТРОГАТЬ
│   ├── hypotheses.py  metrics.py  llm.py  prompts.py
│   ├── runtime.py                 ~ стоп-флаг → per-RunContext (R9)
│   ├── config.py                    Settings — база для A2ASettings
│   ├── __main__.py                ← python -m blocksnet_agent → A2A-сервис
│   ├── tools/
│   │   ├── __init__.py            ~ make_tools() + exclude-параметр
│   │   ├── catalog.py             ← ToolSpec, build_catalog(), TOOL_BLOCKLIST
│   │   ├── registry.py              RAG-справка — СУЩЕСТВУЕТ, НЕ ТРОГАТЬ
│   │   └── data|network|provision|services|indicators|optimize|viz.py
│   └── a2a/                       ← новый пакет
│       ├── __main__.py  server.py  agent_card.py  task_manager.py
│       ├── settings.py  schemas.py  auth.py  context.py
│       └── skills/{__init__,run_pipeline,analyze_urban_question}.py
│
├── blocksnet_mcp/
│   ├── __init__.py                ~ реэкспорт без обязательного LLM-импорта
│   ├── __main__.py                ← python -m blocksnet_mcp
│   ├── server.py                  ~ динамическая регистрация из catalog
│   ├── session.py                 ← SessionStore (TTL + LRU)
│   ├── envelope.py                ← конверт ответа + классификация ошибок
│   ├── agent_tool.py              ← бывший tools_mcp.py, [DEPRECATED], флаг
│   ├── context.py  auth.py        ← scenario_id/project_id, Bearer
│   ├── settings.py                ~ LLM-поля убраны из required
│   └── serialize.py                 без изменений
│
├── docs/
│   ├── a2a_refactor/                этот пакет + implementation/
│   ├── a2a_agent_card.md          ← новый
│   ├── mcp_tool_catalog.md        ← генерируется
│   ├── tool_contract.md           ~ v2
│   └── architecture.md  deployment.md  WIKI-LLM.md   ~ обновляются
│
├── tests/
│   ├── test_tool_catalog.py       ← новый
│   ├── test_mcp_session.py        ← новый
│   ├── test_mcp_tool_exposure.py  ← новый
│   ├── test_a2a_card.py  test_a2a_skills.py  test_a2a_auth.py   ← новые
│   ├── test_runtime_stop_scope.py ← новый (R9)
│   └── test_*.py                    существующие — должны остаться зелёными
│
├── scripts/
│   ├── smoke_mcp_tools.py  smoke_a2a_agent.py  smoke_docker.sh   ← новые
│   └── generate_tool_catalog.py   ← новый
│
├── Dockerfile.agent  Dockerfile.mcp  docker-compose.yml  .dockerignore  ←
├── pyproject.toml                 ← extras [agent] / [mcp]
└── requirements.txt  README.md    ~
```

## 4. Режимы деплоя

| Режим | A2A-сервис | MCP-сервер | Когда |
|---|---|---|---|
| Local dev | не нужен | `python -m blocksnet_mcp` (stdio) | Claude Desktop / Cursor / отладка tools |
| Local agent | `python -m blocksnet_agent` (uvicorn) | опционально, независимо | разработка агента |
| Docker local | контейнер `blocksnet-agent` | контейнер `blocksnet-mcp` | `docker compose up` |
| MAS staging | HTTP + Bearer + scenario_id | HTTP + Bearer + scenario_id | staging |
| MAS prod | HTTP + JWT + scenario_id | HTTP + JWT + scenario_id | prod |

Оба сервиса запускаются **независимо**: MCP не требует агента, агент не
требует MCP.

## 5. Сравнение с текущим состоянием

| Аспект | Сейчас | После |
|---|---|---|
| MCP-инструментов | 1 (`analyze_urban_question`) | 32 raw + 1 deprecated |
| Старт MCP без `CHAT_URL`/`API_KEY` | невозможен | возможен |
| Многошаговая работа через MCP | невозможна | через `session_id` |
| Транспорт | stdio | A2A HTTP + MCP stdio (далее HTTP) |
| Добавление tool | правка агента | 1 модуль, подхватывают оба |
| Детерминированный вызов | невозможен | да |
| A2A-совместимость | нет | Agent Card + 2 skill |
| Конкурентные прогоны | стоп-флаг глобальный | стоп per-run |
| Агент и tools в разных процессах | нет | нет (отложено, см. Q6) |

## 6. Что не меняется

- Выходной JSON `analyze_urban_question` — совместим байт-в-байт
  (поля P1.1, P1.2, P1.6).
- Сигнатуры и текстовый выход всех инструментов.
- `BlocksNetAgent.run()` и работа со `state`.
- Существующие тесты `tests/` — без правок.

## 7. Границы применимости

- Если `a2a-sdk` не подойдёт — заменяется содержимое `blocksnet_agent/a2a/`,
  остальной код не затрагивается.
- Если понадобится несколько реплик MCP — потребуется sticky-сессия или
  внешний session store.
- Если потребуется сетевое разделение агента и tools — отдельная работа
  с дизайном переноса `state`, см.
  [../deferred/a2a_refactor_deferred.md](../deferred/a2a_refactor_deferred.md).
- Если MAS уйдёт с A2A на другой стандарт — меняется адаптер `a2a/`.
