# Рассуждения: почему нужно разделить агент и MCP-сервер

Документ фиксирует текущее состояние `blocksnet-mcp`, проблемы выбранной
ранее архитектуры и мотивацию к рефакторингу. Содержит **только анализ**,
без кода и плана реализации (см. [../plans/a2a_refactor/overview.md](../plans/a2a_refactor/overview.md)).

## 1. Текущее состояние (as-is)

### Архитектура

```text
Локальный MCP-клиент
  -> stdio
  -> blocksnet_mcp.server (FastMCP, 1 tool)
  -> tools_mcp.analyze_urban_question
  -> BlocksNetAgent.run(question)
  -> serialize.to_json(result)
  -> JSON-ответ MCP-клиенту
```

### Файлы и ответственность

| Модуль | Строк | Что делает |
|---|---:|---|
| `blocksnet_mcp/server.py` | 106 | FastMCP-обёртка, async-progress, deadline |
| `blocksnet_mcp/tools_mcp.py` | 147 | Единственный tool `analyze_urban_question`, оборачивает агента |
| `blocksnet_mcp/serialize.py` | 398 | Сериализация результата агента в JSON |
| `blocksnet_mcp/settings.py` | 49 | Конфиг: CHAT_URL, API_KEY, MODEL, DATA_DIR, OUTPUT_DIR, MAX_ITERATIONS |
| `blocksnet_agent/agent.py` | 1299 | **Ядро агента**: PTR-цикл, RAG по tools, инварианты M1-M3/C1-C2-C3, LLM-цикл |
| `blocksnet_agent/hypotheses.py` | 759 | Логика гипотез и overlay layers |
| `blocksnet_agent/metrics.py` | 534 | Метрики качества (M1-M3) |
| `blocksnet_agent/runtime.py` | 302 | Run context, дедлайны, прогресс-колбэки |
| `blocksnet_agent/llm.py` | 41 | LLM-клиент (OpenAI-совместимый) |
| `blocksnet_agent/prompts.py` | 84 | Промпты для LLM |
| `blocksnet_agent/tools/` | 2519 | **33 инструмента** (сверено 2026-07-21, см. ниже) |

Состав `blocksnet_agent/tools/` (факт, не оценка):

| Модуль | Строк | `@tool` | Что внутри |
|---|---:|---:|---|
| `data.py` | 542 | 9 | загрузка кварталов/матрицы, кэш, справки по блокам |
| `optimize.py` | 852 | 3 | `suggest_target_blocks`, `propose_zone_development`, `compute_scenario_provision` |
| `provision.py` | 612 | 2 | `compute_service_provision`, `compute_shared_provision` |
| `network.py` | 177 | 6 | accessibility/connectivity метрики |
| `services.py` | 159 | 6 | плотность, разнообразие, центральность сервисов |
| `indicators.py` | 72 | 3 | density/development индикаторы, adjacency graph |
| `viz.py` | 110 | 1 | `render_metric_map` |
| `registry.py` | 151 | 2 | RAG-справка: `find_tools`, `get_tool_help` |
| `__init__.py` | 194 | — | `make_tools()`: композиция фабрик, мемоизация, streak-лимит RAG |

Итого 30 доменных + 2 RAG = 32, плюс `submit_answer`, добавляемый динамически
в `make_tools()` = **33 в наборе агента**. `submit_answer` — терминальный
инструмент агентского цикла и наружу не экспонируется, поэтому в MCP уходит
**32**.

### Что экспонируется наружу

Один-единственный MCP-tool: `analyze_urban_question(question, max_iterations?)`.
Внутри запускается полный LLM-цикл: модель сама планирует, выбирает tools
из 33, делает PTR-цикл, проверяет инварианты, финализирует JSON.

### Контракт ответа

См. [docs/tool_contract.md](../../tool_contract.md) и README раздел
«Контракт инструмента». Выход — структурный JSON с планом, результатом,
гипотезами, измеренными эффектами, рекомендациями, confidence и артефактами.

## 2. Что не так

### 2.1. Агент и инструменты жёстко связаны

В текущей модели MCP-сервер **сам** запускает LLM-цикл. Это значит:

- Нельзя использовать другой LLM-движок без переписывания `tools_mcp.py`
  и конфига сервера.
- Нельзя дать более умной внешней модели (Claude, GPT-5, Hermes)
  доступ к тем же 33 tools, не повторяя логику PTR-цикла.
- Нельзя сменить стратегию оркестрации (например, добавить multi-step
  planning, hypothesis overlay layers, второй уровень рефлексии) —
  клиент видит только финальный JSON, не имеет доступа к трассе.

### 2.2. Добавление нового tool = правка агента

Сейчас новые tools в `blocksnet_agent/tools/` появляются регулярно (см.
коммит `a6a1b5f Agent/runtime hardening, hypothesis overlay layers, and
repo cleanup`). Но чтобы tool стал доступен клиенту, его нужно:

1. Реализовать в `tools/<name>.py`.
2. Зарегистрировать в `tools/__init__.py`.
3. Пройти через LLM-цикл агента, который выбирает его на основе
   RAG-описания.

Шаг (3) делает невозможным прямой deterministic-вызов из внешнего
клиента (например, из CI-теста или из pipeline, который знает точно,
какой tool нужен). Любой вызов = «прогнать агента с нуля».

### 2.3. LLM-конфиг сидит в MCP-сервере

`settings.py` требует `CHAT_URL` / `API_KEY` / `MODEL`. Это правильно,
когда агент живёт в MCP, но создаёт зависимость транспорта (stdio)
от облачного провайдера. В MAS-сценарии (HTTP + Bearer + scenario_id)
это **конфликтует** с разделением transport/auth/business-logic.

### 2.4. MAS-план требует двух разных контуров

[docs/mas_integration_implementation../plans/a2a_refactor/overview.md](../plans/mas_integration.md)
уже описывает этапы 1–10 для превращения локального MVP в сетевой
сервис. Но в нём **агент остаётся частью MCP-сервера** — это усложняет
независимое развитие:

- Transport/auth (этапы 1–3) зависят от LLM-конфига в `settings.py`
- UrbanDB-адаптер (этап 4) вынужден тащить `CHAT_URL`/`API_KEY` как
  обязательные зависимости, хотя для materialization данных они не нужны
- Contract v2 (этап 5) приходится пересогласовывать с логикой
  `BlocksNetAgent.run()`, а не с автономным API

### 2.5. Главное ограничение: tools — не изолированные функции

Добавлено по итогам сверки с кодом 2026-07-21. Это ограничение не было учтено
в первой редакции документа и оно определяет форму решения.

**Инструменты замкнуты над общим мутабельным `state`.**
`make_tools(state, data_dir, output_dir)` создаёт их фабриками, каждая
захватывает `ctx["state"]`. `load_*` и `compute_*` пишут результаты в
`state[result_key]`; `get_analysis_results`, `get_metric_for_block`,
`render_metric_map`, `list_cached_data` их оттуда читают. Вызов
`get_analysis_results("provision_school")` без предшествующего
`compute_service_provision("school")` **в той же сессии** вернёт «не найден».

**Тот же `state` читает и постобработка агента.** Это уже не про tools:

- `overlay_candidates(hypothesis_ledger, self._state)` — источник P1.6
  `recommendation_blocks`; при пустом `state` слои молча отбрасываются
  (`if layer.result_key not in state: continue`);
- численная верификация гипотез (P1.3) адресуется в `state[result_key]`,
  иначе деградирует до «последнее число из прозы»;
- `_parse_output(..., _state_ref=self._state)` собирает `confidence_basis` (P1.2);
- `valid_block_ids` (P0.5) берётся из `state["blocks"]`.

**Следствие для архитектуры.** Разделить агента и tools границей процесса
нельзя «просто обернув транспорт»: отказ будет тихим — не исключение, а
деградация качества ответа при зелёных тестах. Поэтому целевая схема —
не «агент → MCP → tools», а два **равноправных** потребителя одной фабрики
инструментов (см. [open_questions.md](open_questions.md), Q6). Сетевое
разделение агент↔tools остаётся целью, но выносится в отдельную работу
с явным дизайном переноса состояния.

## 3. Целевое состояние (to-be)

### 3.1. Высокоуровневая идея

**Агент становится самостоятельным A2A-сервисом; MCP-сервер становится
независимым тонким фасадом над теми же инструментами — соседом агента,
а не его подложкой.**

```text
   Hermes / любой A2A-клиент          Claude Desktop / Cursor / CI
              │                                    │
              │ A2A JSON-RPC (HTTP)                │ MCP (stdio, далее HTTP)
              ▼                                    ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│ blocksnet-agent-service (A2A)    │   │ blocksnet-mcp (raw tools)        │
│ - Agent Card (/.well-known/...)  │   │ - 32 tool из make_tools():       │
│ - skills:                        │   │    • load_blocks                 │
│    • run_pipeline (multi-step)   │   │    • load_accessibility_matrix   │
│    • analyze_urban_question      │   │    • compute_service_provision   │
│      (обёртка, back-compat)      │   │    • compute_shared_provision    │
│ - tasks / messages / artifacts   │   │    • compute_scenario_provision  │
│ - Bearer / MAS auth              │   │    • suggest_target_blocks       │
│ - scenario_id / project_id       │   │    • propose_zone_development    │
│                                  │   │    • render_metric_map           │
│ ┌──────────────────────────────┐ │   │    • find_tools / get_tool_help  │
│ │ BlocksNetAgent (не меняется) │ │   │    • ... (полный список — в      │
│ │  PTR · RAG · инварианты ·    │ │   │      mcp_tool_catalog.md)        │
│ │  hypotheses · state          │ │   │ - SessionStore: session_id→state │
│ └──────────────┬───────────────┘ │   │ - НЕТ LLM, гипотез, PTR-цикла    │
└────────────────┼─────────────────┘   └────────────────┬─────────────────┘
                 │                                      │
                 └──── blocksnet_agent.tools.catalog ────┘
                        make_tools(state, dirs) — одна фабрика,
                        у каждого процесса свой state
                                     │
                                     ▼
                     blocksnet (расчёты) + DATA_DIR
```

`submit_answer` (33-й инструмент) остаётся только у агента: он терминальный
и завершает PTR-цикл.

### 3.2. Что это даёт

| Выигрыш | Как именно |
|---|---|
| **Переиспользование инструментов** | Любой MCP-клиент (не только наш агент) зовёт 32 tool |
| **Добавление нового tool = 1 файл** | `tools/<name>.py` + строка в фабрике — подхватывают и агент, и MCP |
| **Агент развивается независимо** | Смена модели, новые skills, overlay — без правки MCP |
| **A2A-стандарт** | Готовый Agent Card, message protocol, artifact streaming — не изобретаем |
| **MAS-интеграция упрощается** | MAS общается с A2A-агентом; MCP доступен отдельно для детерминированных шагов |
| **MCP стартует без LLM** | `CHAT_URL`/`API_KEY` больше не обязательны для запуска MCP |
| **Deterministic-only режим** | CI/тесты вызывают tools через MCP без LLM |
| **Обратная совместимость** | `analyze_urban_question` есть и как A2A-skill, и (deprecated) как MCP-tool |

### 3.3. Что НЕ меняется

- **Ядро `blocksnet_agent/agent.py`** (PTR, RAG, инварианты, работа со `state`)
  — не трогаем; A2A-слой оборачивает его снаружи.
- **Сигнатуры и текстовый выход всех 33 инструментов** — без изменений
  (см. [open_questions.md](open_questions.md), Q5).
- **Контракт `analyze_urban_question`** — тот же JSON, теперь доступен
  через A2A-skill и через MCP-tool (deprecated).
- **Существующие тесты** в `tests/` — продолжают работать без правок.
- **MAS-план** в `mas_integration_implementation../plans/a2a_refactor/overview.md` — расширяется,
  а не переписывается.

Единственное исключение: глобальный стоп-флаг в `runtime.py` переезжает
в `RunContext` — без этого A2A не может обслуживать задачи параллельно
(отмена одной остановит все). См. [review.md](review.md), R9.

## 4. Альтернативы, которые были отклонены

### 4.1. «Оставить как есть, просто добавить HTTP-транспорт»

Соответствует этапам 1–3 MAS-плана без рефакторинга. Минусы:
- LLM-конфиг в MCP-сервере остаётся (см. 2.3)
- Добавление tools по-прежнему требует прохождения через агента
- Нет способа вызвать tools детерминированно

### 4.2. «Вынести все 33 tools как отдельные MCP-tools, агент — отдельный сервис»

Самый радикальный вариант: MCP-сервер вообще не знает про агента.
Минусы:
- Ломается обратная совместимость: `analyze_urban_question` исчезает
- Каждый клиент должен сам реализовать PTR-цикл
- Удвоение работы: тот же pipeline пришлось бы писать и в агенте
  (для автономного режима), и в каждом клиенте (для интеграционного)

### 4.3. «Вынести агент в отдельное репо»

Предложение обсуждалось, но для текущей фазы отклонено:
- Дублирование CI-конфига, тестов, зависимостей
- Усложнение синхронизации версий (агент ↔ MCP-сервер)
- Моно-репо проще для 1-2 разработчиков, разделение можно сделать позже
- Решается **сейчас** через чёткую структуру папок + два Dockerfile
  в одном репо

## 5. Связь с уже существующими документами

| Документ | Как связан |
|---|---|
| [README.md](../../README.md), раздел «Концепция → Вариант 2» | **Пересматривается**. Вариант 2 («обернуть агента целиком») заменяется на A2A+MCP |
| [docs/../architecture/target_architecture.md](../architecture/target_architecture.md) | **Дополняется** новой диаграммой (см. [../architecture/target_architecture.md](../architecture/target_architecture.md)) |
| [docs/tool_contract.md](../../tool_contract.md) | **Расширяется** до v2: A2A-skills + MCP tool catalog |
| [docs/mas_integration_implementation../plans/a2a_refactor/overview.md](../plans/mas_integration.md) | **Расширяется**: этапы 1–7 частично перераспределяются между A2A-сервисом и MCP-сервером |
| [examples/](../../examples/) (`city_picker.py`, `_lib/run_mcp.py`) | **Не меняется** — зовут `analyze_urban_question`, который сохраняется в MCP как deprecated (Q7) |

## 6. Следующий шаг

- [review.md](review.md) — что в этом документе было неточно и почему.
- [open_questions.md](open_questions.md) — Q1–Q7 с принятыми решениями.
- [../plans/a2a_refactor/overview.md](../plans/a2a_refactor/overview.md) — дорожная карта, и далее
  [implementation/](implementation/) — пошаговое исполнение.

---

*Ред. 2026-07-21: §1 выверен по коду, добавлен §2.5 (state-связанность),
§3.1 перерисован под sibling-топологию, имена инструментов исправлены на
фактические. Мотивационная часть (§2.1–2.4, §4) — из исходной редакции,
подтверждена без изменений.*
