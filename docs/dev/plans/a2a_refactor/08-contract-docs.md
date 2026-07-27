# Шаг 08 — Контракт v2 и документация

**Цель.** Внешний интегратор подключается, читая только документацию, без
чтения кода.

**Предусловия.** Шаги 03, 05, 06, 07.

**Оценка.** 1 день.

---

## Задачи

### 8.1. `scripts/generate_tool_catalog.py` → `docs/mcp_tool_catalog.md`

Генерирует каталог из `build_catalog()`: имя, короткое описание, JSON Schema
входа, полная справка (из RAG-реестра), пометка «требует сессии» для
инструментов, читающих `state[result_key]`.

Каталог **генерируемый** — в шапке файла явная пометка «не редактировать
руками, источник — `scripts/generate_tool_catalog.py`».

Добавить тест `tests/test_tool_catalog_docs.py`: сгенерированный контент
совпадает с закоммиченным (иначе каталог протухнет через две недели).

### 8.2. `docs/tool_contract.md` → v2

Дописать разделы, **не удаляя v1** (на него ссылаются существующие тесты
и потребители):

- «A2A Skills»: `run_pipeline` (вход, события, артефакты, терминальные
  статусы), `analyze_urban_question` (вход/выход — прежний контракт v1);
- «MCP Tool Catalog»: конверт ответа, коды ошибок, ссылка на каталог;
- «Сессии MCP»: `session_id`, поведение по умолчанию, TTL/LRU,
  `open/close/info`, `SESSION_SCENARIO_MISMATCH`;
- «Auth и scenario_id»: 401/403, `SCENARIO_NOT_MATERIALIZED`;
- «Совместимость»: таблица «что было в v1 → где это в v2», отдельной
  строкой — `analyze_urban_question` как MCP-tool со статусом deprecated
  и планом удаления в v2.1.

### 8.3. `docs/a2a_agent_card.md`

Пример карточки (реальный вывод сервиса, не выдуманный), описание каждого
поля, как клиенту её получить, версия SDK из `spike-a2a.md`.

### 8.4. Обновление существующих документов

| Файл | Что |
|---|---|
| `README.md` | раздел «Концепция»: убрать «Вариант 2» (обёртка агента целиком), описать два сервиса; обновить quickstart — теперь два входа: `python -m blocksnet_mcp` и `python -m blocksnet_agent` |
| `docs/architecture.md` | целевая диаграмма из [../../architecture/target_architecture.md](../../architecture/target_architecture.md) §1 |
| `docs/deployment.md` | запуск обоих сервисов, переменные окружения (таблица: кому какая нужна), docker compose, размеры образов |
| `docs/WIKI-LLM.md` | новые пакеты `blocksnet_agent/a2a`, `blocksnet_mcp/session|envelope|agent_tool` |
| `docs/mas_integration_implementation_plan.md` | отметить, какие этапы закрыты шагами 06–07, что осталось (e2e, hardening, handoff) |
| `blocksnet_mcp/README.md`, `blocksnet_agent/README.md` | привести в соответствие |

### 8.5. Переменные окружения — единая таблица

В `docs/deployment.md`, с колонкой «кому нужна»:

| Переменная | Агент | MCP | Обязательна | По умолчанию |
|---|---|---|---|---|
| `CHAT_URL`, `API_KEY` | да | нет¹ | для агента | — |
| `MODEL` | да | нет | нет | `gpt-4o-mini` |
| `DATA_DIR`, `OUTPUT_DIR` | да | да | нет | `./data`, `./outputs` |
| `MAX_ITERATIONS` | да | нет | нет | `24` |
| `DEADLINE_SEC` | да | да | нет | `480` |
| `SESSION_TTL_SEC`, `MAX_SESSIONS` | нет | да | нет | `1800`, `8` |
| `ENABLE_AGENT_TOOL` | нет | да | нет | `true` |
| `A2A_HOST/PORT/PUBLIC_URL` | да | нет | нет | `0.0.0.0`/`8080` |
| `AUTH_ENABLED`, `MAS_BEARER_TOKEN` | да | да | нет | `false` |
| `URBANDB_URL`, `URBANDB_TOKEN` | да | да | при `scenario_id` | — |

¹ только для deprecated `analyze_urban_question`.

### 8.6. Отчёт о завершении

`docs/reports/a2a_refactor_completion_report.md` (формат — как у соседних
отчётов в `docs/reports/`): что сделано по шагам, отклонения из
`deviations.md`, фактические числа (инструментов экспонировано, тестов
добавлено, размеры образов), что осталось (ссылка на
[../../deferred/a2a_refactor_deferred.md](../../deferred/a2a_refactor_deferred.md)).

### 8.7. Архивация

`docs/a2a_refactor/` → `docs/archive/a2a_refactor/` **после** приёмки,
сохранив относительные ссылки рабочими (проверить `grep -r "a2a_refactor"`).

---

## DoD

- [ ] `python scripts/generate_tool_catalog.py` — `docs/mcp_tool_catalog.md`
      сгенерирован и закоммичен
- [ ] `python -m pytest tests/test_tool_catalog_docs.py -q` — зелёный
- [ ] `docs/tool_contract.md` содержит v1 **и** v2
- [ ] Все ссылки живые: `grep -oE "\]\([^)#]+\.md" docs -r` — каждый путь существует
- [ ] README читается за один экран и ведёт к обоим сервисам
- [ ] Отчёт написан
- [ ] Коммит `a2a/08: contract v2 and documentation`

## Не делать

- Не удалять v1-контракт.
- Не редактировать `mcp_tool_catalog.md` руками.
- Не архивировать `docs/a2a_refactor/` до приёмки Игорем.

## Откат

Документация не влияет на код — откат тривиален.
