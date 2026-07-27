# Индекс `tests/`

Назначение: контрактные тесты MCP-server и unit-тесты сериализации/пайплайна.

Тесты проверяют тонкий слой обёртки и структурные части рассуждающего ядра (submit_answer,
P1.2-confidence, P1.6-overlay, кэш provision, PTR-классификатор), а **не** качество LLM-рассуждения
в целом. Для поведения агента источник истины — в `blocksnet_agent/` и upstream-проекте
`blocksnet-agent`.

## Тесты

| Файл | Что проверяет |
|---|---|
| `test_serialize.py` | Преобразование `AgentResult` → JSON-контракт: P1.1 `submit_answer` приоритет, P1.2 `confidence` + `confidence_self` + `confidence_basis`, P1.6 `overlay_candidates`, regex-fallback с `salvaged: true` |
| `test_tool_contract.py` | Входные параметры и обязательные поля выхода `analyze_urban_question` |
| `test_async_mcp_contract.py` | Async-обёртка FastMCP: `notifications/progress`, корректная работа с `DEADLINE_SEC`, `status="partial"` вместо `ExceptionGroup` |
| `test_runtime.py` | `runtime.start_run`: `run_id`, deadline, прогресс, прогресс-callback |
| `test_confidence_signals.py` | P1.2-формула `confidence_basis`: какие сигналы дают какой вклад, сохранение `confidence_self` |
| `test_overlay_candidates.py` | P1.6: overlay-кандидаты из гипотез-слоёв, hard_passed/diagnostic_layers, fallback в `recommendation_blocks` |
| `test_ptr_classifier.py` | PTR-классификатор гипотез: `supported` / `refuted` / `inconclusive` |
| `test_provision_cache.py` | T1.2-мемоизация `compute_*` / `list_*` / `load_*`; `compute_scenario_provision` и `list_cached_data` намеренно не мемоизируются |
| `test_numeric_metric_resolution.py` | Резолвер числовых метрик по `state` (имена колонок, алиасы) |
| `test_provision_summaries.py` | Сводки по `compute_service_provision` (город/квартал/сервис) |
| `test_target_block_selection.py` | Логика `suggest_target_blocks` (валидные критерии, отбраковка невалидных) |
| `test_tool_failure_dedup.py` | Дедупликация повторных failed-вызовов (P0.4: invalidation по версии state) |
| `test_no_data_grounding.py` | Поведение при отсутствии данных: `NO_DATA` маркеры, явные `limitations` |
| `test_experiment_harness.py` | Локальный harness для прогона экспериментов на `examples/saint_petersburg/` |

## Запуск

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

Текущий результат в локальном окружении Python `3.10.11`: все тесты `passed`. Полный отчёт по
качественным прогонам 06.07.2026 — в `../docs/reports/run_quality_report_20260706_spb.md`.

## Минимальные проверки (MCP-контракт)

- `question` обязателен и остаётся в ответе.
- `analysis_plan`, `result`, `reflection`, `recommendations`, `measured_effects`, `confidence`,
  `confidence_self`, `confidence_basis`, `limitations`, `artifacts`, `run_id`, `run_dir`, `status`
  имеют ожидаемые типы.
- При `submit_answer`: `salvaged: false`; `recommendation_blocks` извлекается из `recommendations[].block_id`.
- В fallback-пути: `salvaged: true`, в `limitations` присутствует `SALVAGED_ANSWER`,
  `overlay_candidates` / `overlay_meta` приходят из `overlay_candidates` (если слои были).
- `hypotheses[].status` (где присутствует, в fallback-пути) ограничен значениями
  `supported` / `refuted` / `inconclusive`.
- Сериализация не требует парсинга длинного нарратива потребителем.
