# Соответствие `blocksnet-agent` контракту CodeSynapse

Дата сверки: **2026-07-28**. Профиль: **A2A 1.0**
(`docs/dev/codesynapse/docs/contracts/a2a/synapse-a2a-1.0.schema.json`).

Статусы — те же, что в вашем каталоге полей, и в том же смысле:

- `supported` — обрабатывается без известной потери семантики;
- `partial` — принимается, но часть данных или поведения теряется;
- `planned` — входит в целевой контракт, реализация не завершена;
- `not-applicable` — отдельной обработки не требует.

Каждая строка «supported» подтверждается запускаемым тестом. Прогон:

```bash
pytest -q tests/test_codesynapse_contract.py tests/test_codesynapse_mcp.py
python scripts/validate_agent_card.py
```

---

## 1. Agent Card

| Требование | Статус | Чем подтверждено |
|---|---|---|
| Карточка валидна по `$defs.agentCard` | supported | `test_agent_card_validates_against_synapse_schema` — 0 расхождений |
| Обязательные поля 1.0 | supported | `test_agent_card_has_required_fields` |
| `protocolVersion` строго `"1.0"` | supported | `test_agent_card_protocol_version_is_exactly_1_0` |
| Нет legacy-полей 0.3 | supported | `test_agent_card_has_no_legacy_03_fields` |
| Нет полей вне закрытой схемы | supported | `test_agent_card_declares_no_fields_outside_schema` |
| `defaultOutputModes` понятны Synapse | supported | `test_declared_output_modes_are_understood_by_synapse` |
| `AgentCardSignature` | planned | подписи не выставляем; у вас они и не проверяются |
| `provider`, `iconUrl`, `documentationUrl` | not-applicable | не заполняем |

## 2. Параметры запуска (Profile Extension)

| Требование | Статус | Чем подтверждено |
|---|---|---|
| Required extension со схемой параметров | supported | `test_parameter_extension_matches_synapse_profile`, `test_parameter_extension_is_required` |
| Схема — валидный JSON Schema | supported | `test_parameter_schema_is_a_valid_json_schema` |
| Схема переживает protobuf-сериализацию | supported | `test_parameter_schema_survives_protobuf_roundtrip` |
| Типы согласованы с нашим контекстом | supported | `test_parameter_names_match_the_scenario_context_contract` |
| Параметры читаются из DataPart | supported | `test_data_part_parameters_are_parsed` + тест на подключение |
| DataPart побеждает при конфликте | supported | `test_data_part_wins_over_metadata_on_conflict` |
| Текст интента доезжает неизменным | supported | `test_question_text_reaches_the_agent_unchanged` |
| Отсутствующие параметры не выдумываются | supported | `test_absent_parameters_are_not_fabricated` |
| Обязательные параметры | not-applicable | их нет осознанно — см. §6, вопрос 5 |

## 3. Выполнение и результат

| Требование | Статус | Чем подтверждено |
|---|---|---|
| Ответ — `Task`, валидный по `$defs.task` | supported | `test_completed_task_validates_against_schema` |
| Не «message mode» | supported | `test_response_is_a_task_not_a_bare_message` |
| Статусные события валидны по `$defs.taskStatusUpdate` | supported | `test_status_update_event_validates_against_schema` |
| Значения `TASK_STATE_*` | supported | `test_status_events_use_1_0_task_state_names` |
| Нет legacy-поля `final` | supported | `test_status_events_carry_no_legacy_final_field` |
| Причина отказа в `TaskStatus.message` | supported | `test_failed_run_reports_reason_in_task_status_message` |
| Без traceback наружу | supported | `test_failure_message_carries_no_traceback` |
| Отказ до расчёта при невалидном параметре | supported | `test_invalid_parameter_fails_before_the_run` |
| `TASK_STATE_CANCELED` по отмене | supported | обработка отмены в `_A2ATaskBridge.cancel` |
| `TASK_STATE_INPUT_REQUIRED` | not-applicable | не эмитим: у вас это тупик (`a2a_input_required`, SYNAPSE-181) |
| `TASK_STATE_REJECTED`, `TASK_STATE_AUTH_REQUIRED` | planned | ваш каталог помечает их обработку как недоведённую — не используем |
| `pushNotifications` | planned | объявлено `false`; вне профиля |
| Streaming | partial | `streaming: true` объявлен, поток статусов чинён и валиден, но ваш клиент форсирует non-streaming для всех агентов, поэтому в вашем контуре не используется |

## 4. Артефакты

| Требование | Статус | Чем подтверждено |
|---|---|---|
| Артефакты валидны по `$defs.artifact` | supported | `test_artifacts_carry_content_not_local_paths` |
| Содержимое, а не локальные пути | supported | тот же тест — проверяет отсутствие путей в ответе |
| `Part.data` для структурированного результата | supported | `test_artifacts_carry_content_not_local_paths` |
| Встраивание текстовых/табличных файлов | supported | `test_small_text_artifact_is_embedded` |
| Крупные файлы не теряются молча | supported | `test_oversized_artifact_is_skipped`, `test_unembeddable_artifacts_are_reported_not_dropped` |
| Растровые карты (`.png`) | **partial** | не встраиваются; перечисляются в `skipped_artifacts` — см. §6, вопрос 2 |
| `Part.raw` / `Part.url` | planned | не используем: у вас обоим статус `partial` |
| Целые числа в `Part.data` | **partial** | protobuf `Struct` хранит числа как double, поэтому `[1,2,3]` приезжает `[1.0,2.0,3.0]`. Семантика сохраняется, тип — нет. Обойти в рамках `Struct` нельзя |

## 5. MCP-канал

| Требование | Статус | Чем подтверждено |
|---|---|---|
| Имена инструментов проходят `mcp_tool_ids` | supported | `test_tool_names_satisfy_mcp_segment_rules` |
| `server.tool` укладывается в лимит 64 | supported | `test_public_tool_ids_fit_the_llm_function_name_limit` |
| `tools/list` без смонтированных данных | supported | `test_stdio_server_lists_tools_without_a_dataset` |
| Каталог совпадает с экспонированным | supported | `test_exposed_names_match_the_catalog` |
| Холодная сессия не роняет вызов | supported | `test_cold_session_reports_instead_of_crashing` |
| Изоляция сессий | supported | `test_sessions_do_not_share_state` |
| Сетевой режим (streamable-http) | planned | сейчас stdio-only — см. §6, вопрос 1 |

---

## 6. Открытые вопросы

По каждому — наш вариант, цена альтернативы и дата, после которой мы фиксируем
вариант по умолчанию. Просьба ответить до **2026-08-11**.

### Вопрос 1. Нужен ли MCP по сети?

**Наш вариант:** оставить `stdio` + Docker Image. Он уже работает, не требует
публичного DNS и обходит ваш SSRF-фильтр конструктивно.

**Альтернатива:** `remote/streamable-http` по вашему эталону. Цена — переписать
entrypoint (`mcp.run(transport="stdio")` жёстко), опубликовать порт, поднять
сервис за публичным DNS или добавить хост в `EXTERNAL_MCP_ENDPOINT_ALLOWLIST`.
Оценка: 1–2 дня с проверкой.

**Если ответа нет:** остаёмся на stdio.

### Вопрос 2. Нужны ли растровые карты как артефакты?

**Наш вариант:** не встраивать. `render_metric_map` даёт PNG, у `Part.raw` в
вашем каталоге статус `partial` («не всегда восстанавливается как исходный
файл»), а base64 на несколько мегабайт в каждом ответе — молчаливое раздувание
трафика. Сейчас такие файлы перечислены в `skipped_artifacts` с причиной.

**Альтернатива:** встраивать `Part.raw` с лимитом размера (скажем, 2 MB) либо
отдавать `Part.url`, если у вас есть доступное обеим сторонам файловое
хранилище. Оценка: несколько часов на любой из вариантов.

**Если ответа нет:** оставляем как есть — карты доступны в `run_dir` на нашей
стороне.

### Вопрос 3. Какой таймаут ставить?

**Наш вариант:** `request_timeout_seconds: 300` у вас, `DEADLINE_SEC=280` у нас,
чтобы дедлайн срабатывал на нашей стороне и вы получали внятный
`TASK_STATE_FAILED` вместо разрыва соединения.

**Чего не хватает:** реального замера. Полного датасета (СПб
`blocks_with_services.gpkg`, 336 MB) в репозитории нет, поэтому время прогона на
вашем контуре не измерено. Если типовой прогон не укладывается в 300 секунд,
синхронный вызов нам не подходит вовсе, и разговор переходит к
`pushNotifications`, которые у вас вне профиля.

**Если ответа нет:** ставим 300/280 и фиксируем как известный риск.

### Вопрос 4. Что подставлять в `scenario_id`?

**Контекст:** UrbanDB к сервису не подключён и подключаться не планируется —
blocksnet работает на специфично подготовленных данных, которых UrbanDB не
отдаёт. Поэтому `scenario_id` означает **имя подготовленного датасета на нашем
volume**, а не идентификатор сценария в вашей системе.

**Наш вариант:** оставить параметр необязательным. Один датасет на инстанс —
`scenario_id` не передаётся вовсе; несколько — передаётся имя каталога.
Несуществующее имя даёт `SCENARIO_NOT_MATERIALIZED` со списком доступных.

**Что нужно от вас:** подтвердить, что ваш конвейер не будет автоматически
подставлять сюда внутренний scenario id проекта — он не разрешится. Если
подстановка неизбежна, нам нужна таблица соответствия «ваш scenario id → наш
датасет», и это отдельная небольшая работа.

**Если ответа нет:** оставляем необязательным.

### Вопрос 5. Делать ли `scenario_id` обязательным?

**Наш вариант:** оставить необязательным. Без него анализ идёт на датасете по
умолчанию, что осмысленно для одногородской установки и локальных прогонов.

**Альтернатива:** добавить `scenario_id` в `required` схемы расширения — тогда
ваш клиент упадёт **до** обращения к нам, если сценарий не назван. Цена: одна
строка у нас; риск: ломаются все запросы без явного сценария.

**Если ответа нет:** оставляем необязательным.

---

## 7. Что осталось непроверенным

Честный список — эти пункты подтверждены только на стендовых данных:

- **UrbanDB не подключён — и не планируется.** blocksnet работает на специфично
  подготовленных данных, которых UrbanDB не отдаёт. Практическое следствие:
  датасеты кладутся на volume заранее, а `scenario_id` адресует их по имени
  каталога (§6, вопрос 4). Автоматического пути «сценарий MAS → данные» нет.
- **Прогон против живого CodeSynapse не выполнялся.** Все проверки идут против
  ваших схем и вашего клиентского кода из snapshot `docs/dev/codesynapse/`, но
  не против работающего экземпляра платформы.
- **Время выполнения на реальном датасете не измерено** (вопрос 3).
- **Авторизация проверена только на нашей стороне** — сквозной прогон с вашим
  bearer/OAuth2 не делался.
- Snapshot вашего репозитория зафиксирован на состоянии 2026-07-28; при
  расхождении с вашей текущей версией наши тесты этого не заметят.
