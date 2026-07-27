# Ревью пакета документов `docs/a2a_refactor/`

Дата ревью: 2026-07-21. Ревьюер: агент, сверка документов с фактическим кодом
(`blocksnet_agent/`, `blocksnet_mcp/`, `tests/`, `examples/`, `scripts/`).

Вывод: **мотивация (reasoning.md) верна, целевая архитектура — нет.** Пакет
описывает разделение агента и tools по границе процесса, но код такого
разделения не допускает без отдельной проектной работы, которая в документах
не упомянута. Ниже — 13 находок с указанием места в коде; после каждой —
что именно исправлено в документах.

Легенда severity: **BLOCKER** — план в текущем виде приведёт к поломке или
к невыполнимому критерию приёмки; **MAJOR** — исполнитель потратит время
впустую или примет неверное решение; **MINOR** — неточность.

---

## R1. BLOCKER — tools не stateless, это замыкания над общим `state`

**Что в документах.** `reasoning.md` §3.1 и `../architecture/target_architecture.md` §2.1 описывают
MCP-слой как «33 детерминированных функции», не знающие ни о чём, кроме
`DATA_DIR`. Подразумевается stateless-вызов вида `tool(args) -> result`.

**Что в коде.** [blocksnet_agent/tools/__init__.py:171](../../blocksnet_agent/tools/__init__.py#L171) —
`make_tools(state: dict, data_dir, output_dir)`: все инструменты создаются
фабриками `make_*_tools(ctx)` и **замыкаются** над мутабельным `state`:

- [tools/data.py:203-206](../../blocksnet_agent/tools/data.py#L203-L206) — `state = ctx["state"]`
- `load_blocks()` → `ensure_blocks(state, data_dir)` кладёт GeoDataFrame в `state`
- `compute_*` кладут результат в `state[result_key]`
- `get_analysis_results(result_key)`, `get_metric_for_block(result_key, …)`,
  `render_metric_map(result_key)` **читают** `state[result_key]` и без
  предшествующего `compute_*` в **той же** сессии бессмысленны
- `list_cached_data()` вообще возвращает содержимое `state`

Обращений к `state[...]` в tools: data 8, network 8, services 8, provision 9,
optimize 5, indicators 5, viz 2.

**Последствие.** MCP-сервер, экспонирующий эти функции «как есть», отдаст
на 12+ инструментах «Кэш пуст / сначала вызови load_blocks()». Ни один
многошаговый сценарий не отработает.

**Исправление.** Введена явная модель сессий в MCP (новый Q4, шаг
[02-session-store.md](../plans/a2a_refactor/02-session-store.md)): `session_id` →
`{state, data_dir, output_dir}` c TTL и LRU-лимитом, параметр `session_id`
инжектится в сигнатуру каждого MCP-tool. Формулировка «детерминированные
stateless функции» в reasoning/architecture заменена на «детерминированные
(без LLM) функции, работающие в рамках сессии».

---

## R2. BLOCKER — агент читает тот же `state`, что пишут tools; граница процесса его ломает

**Что в документах.** `reasoning.md` §3.3 и `../architecture/target_architecture.md` §6: «Ядро
`agent.py` не трогаем», `../plans/a2a_refactor/overview.md` этап 4.2: «в skills вызовы tools идут через
`mcp_client.call_tool(name, args)`», in-process — только *fallback*.

**Что в коде.** `self._state` — общий объект между tools и логикой агента:

- [agent.py:116](../../blocksnet_agent/agent.py#L116) — `make_tools(self._state, …)`
- [agent.py:137](../../blocksnet_agent/agent.py#L137) — `ensure_blocks(self._state, …)` вызывается **самим агентом**
- [agent.py:208](../../blocksnet_agent/agent.py#L208) — `_parse_output(…, _state_ref=self._state)` пишет `_confidence_basis`
- [agent.py:251-255](../../blocksnet_agent/agent.py#L251-L255) — читает `state["_submitted_answer"]`, `state["_confidence_basis"]`
- [agent.py:267](../../blocksnet_agent/agent.py#L267) — `overlay_candidates(hypothesis_ledger, self._state, top_n=10)`
- [agent.py:282](../../blocksnet_agent/agent.py#L282) — `self._state.get("blocks")`
- [hypotheses.py:312-316](../../blocksnet_agent/hypotheses.py#L312-L316) — `if layer.result_key not in state: continue` → слой отбрасывается
- [hypotheses.py:455-464](../../blocksnet_agent/hypotheses.py#L455-L464) — численная проверка гипотез идёт через `state[result_key]`

**Последствие.** Если tools исполняются в другом процессе, у агента `state`
остаётся пустым. Отказ **тихий**, не падение: `overlay_candidates` вернёт
пустой список (P1.6 → `recommendation_blocks` уедет на regex-fallback),
численная классификация гипотез (P1.3) деградирует до «numbers[-1] из прозы»,
`valid_block_ids` (P0.5) опустеет, `confidence_basis` (P1.2) не соберётся.
Тесты `test_overlay_candidates.py`, `test_numeric_metric_resolution.py`,
`test_confidence_signals.py` при этом могут остаться зелёными, потому что
дёргают функции напрямую с готовым `state`. Регресс уйдёт в прод незамеченным.

**Исправление.** Топология развёрнута (новый Q6): агент **не** ходит в MCP.
Tools остаются in-process для агента; MCP-сервер — **параллельный** фасад над
той же фабрикой `make_tools()` со своим SessionStore. Этап 4 старого плана
(«A2A ↔ MCP интеграция») удалён из must-have и переоформлен как отложенный
`MCP_TOOL_PROXY` (требует отдельного дизайна переноса state — см.
[../deferred/a2a_refactor_deferred.md](../deferred/a2a_refactor_deferred.md)).

---

## R3. BLOCKER — `blocksnet_agent/tools/registry.py` уже существует и делает другое

**Что в документах.** `../plans/a2a_refactor/overview.md` 1.2: «Создать `blocksnet_agent/tools/registry.py`
со списком `TOOL_REGISTRY: list[ToolSpec]`»; 1.4: «Мигрировать регистрацию из
ручного списка в `registry.py`»; `../architecture/target_architecture.md` §3 помечает `registry.py`
как `← НОВОЕ`.

**Что в коде.** [tools/registry.py](../../blocksnet_agent/tools/registry.py) —
151 строка, существует, реализует RAG-справку по инструментам:
`split_doc()`, `build_tool_registry()` (короткое описание в `.description`,
полное — в реестр), `make_help_tools()` (`find_tools`, `get_tool_help`),
словарь синонимов сервисов. Никакого «ручного списка» регистрации в
`tools/__init__.py` нет — там композиция фабрик.

**Последствие.** Исполнитель плана перезапишет рабочий файл и снесёт RAG-слой
вместе с `find_tools`/`get_tool_help` и индексом синонимов.

**Исправление.** Новый модуль назван `blocksnet_agent/tools/catalog.py`
(`ToolSpec`, `build_catalog()`), `registry.py` в плане явно помечен как
«не трогать». См. [../plans/a2a_refactor/01-tool-catalog.md](../plans/a2a_refactor/01-tool-catalog.md).

---

## R4. MAJOR — «33 tools» неверно и вынесено в критерий приёмки

**Что в документах.** Число «33» встречается 8 раз, включая критерий
завершения «Все 33 tools доступны как MCP-tools».

**Что в коде.** `@tool`-деклараций: data 9, network 6, services 6, indicators 3,
optimize 3, provision 2, viz 1 = **30 доменных**; плюс `find_tools` и
`get_tool_help` из `registry.py` = 32; плюс `submit_answer`, добавляемый
динамически в [tools/__init__.py:183](../../blocksnet_agent/tools/__init__.py#L183)
через `_build_submit_answer_tool` = 33 в наборе агента.

`submit_answer` — терминальный инструмент агента (пишет `state["_submitted_answer"]`,
завершает PTR-цикл). В MCP его экспонировать нельзя. Итог: **32** к экспозиции,
и это число будет меняться при добавлении инструментов.

**Последствие.** Критерий «33 в `tools/list`» не выполнится никогда.

**Исправление.** Везде «33» → «~32 (30 доменных + 2 RAG); `submit_answer`
исключён». Критерий переписан на самопроверяющийся: тест сверяет экспозицию
MCP с `make_tools()` минус blocklist, без захардкоженного числа.

---

## R5. MAJOR — все tools возвращают текстовую прозу, а не JSON

**Что в документах.** `../plans/a2a_refactor/overview.md` 5.5: «JSON Schema для каждого MCP tool»;
критерий этапа 2: «вызывает 2–3 tools и получает валидный JSON»;
`../architecture/target_architecture.md` §2.3: «MCP tool catalog с JSON Schema».

**Что в коде.** Все 30 доменных инструментов объявлены `-> str` и возвращают
человекочитаемый русский текст (`"Кварталы загружены: 1234 строк…"`,
`"Ошибка при загрузке кварталов: …"`). Структурированного выхода нет ни у
одного. Ошибки тоже строки — [tools/__init__.py:152](../../blocksnet_agent/tools/__init__.py#L152)
(`_tool_error_handler`) возвращает текст, а не исключение.

**Последствие.** «JSON Schema на выход» для 30 инструментов — это либо
переписывание всех tools (высокий риск регресса в агенте, который парсит
эти строки в `metrics.py`/`hypotheses.py`), либо пустая обёртка.

**Исправление.** Новый Q5 с решением: в v2.0 выход остаётся строкой, MCP
оборачивает в `{"status", "text", "session_id", "artifacts"}`. JSON Schema
генерируется **только для входа** (FastMCP выводит её из сигнатуры
автоматически). Структурированный выход — отложенный opt-in v2.1.

---

## R6. MAJOR — риск про «RAG-tools требуют LLM» ложный

**Что в документах.** `../plans/a2a_refactor/overview.md`, таблица рисков: «RAG-tools (`find_tools`,
`get_tool_help`) требуют LLM и не подходят для raw MCP», митигация — «оставить
deterministic variant (`list_tools` без эмбеддингов)».

**Что в коде.** [registry.py:70-77](../../blocksnet_agent/tools/registry.py#L70-L77)
(`_score`) — обычный keyword-матчинг через `re.split` и `in`. Ни эмбеддингов,
ни LLM. Оба инструмента полностью детерминированы и в MCP экспонируются
как есть.

**Реальный риск другой:** `make_help_tools(registry)` требует реестра,
построенного над **живым** набором инструментов, то есть MCP обязан строить
tools через ту же `make_tools()`, а не импортировать функции поштучно.

**Исправление.** Строка риска переписана.

---

## R7. MAJOR — в диаграммах фигурируют несуществующие инструменты

**Что в документах.** `reasoning.md` §3.1 и `../architecture/target_architecture.md` §1 перечисляют
`estimate_repopulation`, `accessibility_matrix`, `join_blocks_services`,
`add_service_capacity`, `optimize_tpe_zones`. `../plans/a2a_refactor/overview.md`, критерий этапа 4:
«A2A-агент вызывает `estimate_repopulation` через MCP-сервер».

**Что в коде.** Ни одного из этих имён не существует. Фактические:
`load_accessibility_matrix`, `compute_service_provision`,
`compute_scenario_provision`, `compute_shared_provision`,
`propose_zone_development`, `suggest_target_blocks`, `render_metric_map`, …

**Последствие.** Исполнитель ищет несуществующий код; критерий приёмки
этапа 4 невыполним буквально.

**Исправление.** Все имена в диаграммах и критериях заменены фактическими.

---

## R8. MAJOR — снос `analyze_urban_question` из MCP ломает 6 известных потребителей

**Что в документах.** `../plans/a2a_refactor/overview.md` 2.4: «Удалить `analyze_urban_question` из
`blocksnet_mcp/tools_mcp.py`». В рисках — «средняя вероятность», без перечня.

**Что в коде** зависит от него:

| Потребитель | Место |
|---|---|
| Реэкспорт пакета | [blocksnet_mcp/__init__.py:3](../../blocksnet_mcp/__init__.py#L3) |
| Contract-тест | [tests/test_tool_contract.py:5](../../tests/test_tool_contract.py#L5) |
| Async-контракт | [tests/test_async_mcp_contract.py:12](../../tests/test_async_mcp_contract.py#L12) |
| Smoke-клиент | [scripts/smoke_client.py:115](../../scripts/smoke_client.py#L115) |
| Раннер примеров | [examples/_lib/run_mcp.py:275](../../examples/_lib/run_mcp.py#L275) |
| Пример города | [examples/city_picker.py:7](../../examples/city_picker.py#L7) |

**Исправление.** Новый Q7: инструмент **остаётся** в MCP как
`blocksnet_mcp/agent_tool.py` под флагом `ENABLE_AGENT_TOOL` (в v2.0 default
`true`, помечен deprecated). LLM-настройки читаются **лениво**, внутри вызова —
это закрывает исходную претензию §2.3 reasoning.md (LLM-конфиг не обязателен
для старта MCP) без слома потребителей. Все 6 мест перечислены в
[../plans/a2a_refactor/03-mcp-server.md](../plans/a2a_refactor/03-mcp-server.md).

---

## R9. MAJOR — глобальный `_stop_event` несовместим с конкурентными A2A-задачами

**Что в документах.** `../plans/a2a_refactor/overview.md` 3.6 предполагает task_manager с очередью
задач и статусами; `../architecture/target_architecture.md` §1 — конкурентная обработка.

**Что в коде.** [runtime.py:29](../../blocksnet_agent/runtime.py#L29) —
`_stop_event = threading.Event()`, один на процесс; `stop_run()` (строка 179)
взводит его глобально, `is_stop_requested()` (184) читают **все** инструменты
([tools/__init__.py:100-104](../../blocksnet_agent/tools/__init__.py#L100-L104)).
В комментарии это зафиксировано осознанно: «Один на процесс, как и раньше».

**Последствие.** Дедлайн или отмена одной A2A-задачи останавливает все
параллельные прогоны в том же процессе.

**Исправление.** Добавлен обязательный шаг
[04-agent-decoupling.md](../plans/a2a_refactor/04-agent-decoupling.md): стоп-флаг
переезжает в `RunContext` (per-run), глобальный остаётся как «stop all»
для shutdown. Без этого A2A нельзя включать конкурентность.

---

## R10. MINOR — третий класс настроек вместо расширения существующих

`../plans/a2a_refactor/overview.md` 3.7 создаёт `blocksnet_agent/a2a/settings.py` с
`CHAT_URL/API_KEY/MODEL`. Такие поля уже есть **дважды**:
[blocksnet_agent/config.py:18-26](../../blocksnet_agent/config.py#L18-L26)
(`Settings`) и [blocksnet_mcp/settings.py:20-22](../../blocksnet_mcp/settings.py#L20-L22)
(`MCPSettings`). Третья копия — гарантированный рассинхрон дефолтов
(`max_iterations` уже задан в двух местах).

**Исправление.** `A2ASettings` наследует `blocksnet_agent.config.Settings`
и добавляет только транспортные поля. Из `MCPSettings` LLM-поля удаляются.

---

## R11. MINOR — `python -m blocksnet_mcp` сегодня не работает

Критерий завершения: «MCP-сервер поднимается через `python -m blocksnet_mcp`».
`blocksnet_mcp/__main__.py` отсутствует; `blocksnet_agent/__main__.py` тоже
(`../architecture/target_architecture.md` §3 показывает его как существующий). Оба добавлены явными
задачами.

---

## R12. MINOR — ссылка на спецификацию A2A и отсутствие пина версии

`open_questions.md` Q1 ссылается на `github.com/a2a-protocol/a2a-spec`.
Канонический репозиторий — `github.com/a2aproject/A2A` (перешёл под Linux
Foundation из `google/A2A`). Версия `a2a-sdk` не зафиксирована, при этом
`../plans/a2a_refactor/overview.md` в предусловиях требует «зафиксирована версия a2a-sdk» — циклическая
зависимость: зафиксировать нечем, проверки нет.

**Исправление.** Ссылка исправлена с пометкой «проверить при спайке»; добавлен
обязательный спайк [00-preflight.md §4](../plans/a2a_refactor/00-preflight.md)
с явным exit-критерием и точным пином в `requirements.txt`.

---

## R13. MINOR — окружение не воспроизводимо, baseline снять нечем

`../plans/a2a_refactor/overview.md` 0.3/0.4: «`pip check` чист», «снять baseline pytest». В текущем
окружении отсутствуют и `pip`, и зависимости (`import mcp` → ModuleNotFoundError),
`pyproject.toml` нет, есть только `requirements.txt`. Шаг 0 не выполним как
написан.

**Исправление.** [00-preflight.md](../plans/a2a_refactor/00-preflight.md) начинается
с создания venv и фиксации baseline в файл; добавлен явный DoD «baseline
сохранён в `docs/a2a_refactor/implementation/baseline.txt`».

---

## Что осталось верным и не менялось

- Мотивация §2.1–2.4 `reasoning.md` — связанность агента и транспорта,
  LLM-конфиг как обязательная зависимость MCP, конфликт с MAS-планом.
- Отклонение альтернатив §4.1–4.3 — аргументация корректна.
- Q3 (моно-репо) — рекомендация принята без изменений.
- Q2 (два skills) — принята с уточнением (см. open_questions.md).
- Разбиение на этапы 5–8 (контракт, auth/context, docker, документация) —
  сохранено, уточнены задачи.

## Сводка изменений в документах

| Документ | Что сделано |
|---|---|
| `reasoning.md` | §1 таблица модулей выверена по коду; добавлен §2.5 (state-связанность как главное ограничение); §3.1 диаграмма перерисована под sibling-топологию; имена tools исправлены |
| `open_questions.md` | Q1–Q3 закрыты решениями; добавлены и закрыты Q4 (сессии), Q5 (формат выхода), Q6 (топология), Q7 (back-compat) |
| `../architecture/target_architecture.md` | Диаграмма, layout, таблицы приведены в соответствие с решениями; добавлен §2.5 про сессии |
| `../plans/a2a_refactor/overview.md` | Сокращён до дорожной карты; пошаговое исполнение вынесено в `implementation/` |
| `README.md` | Обновлён индекс, статус, порядок чтения |
| `implementation/` | Новая папка: 10 файлов пошагового плана под исполнение агентом |
