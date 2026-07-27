# План реализации интеграции `blocksnet-mcp` в MAS

> **Статус a2a-рефакторинга (2026-07):**
> Этапы 2-6 закрыты шагами **03-07 плана a2a-рефакторинга** в
> `docs/a2a_refactor/implementation/`:
> - **Этап 1 (local vs MAS runtime)** — закрыт шагом 04 (per-run stop, settings).
> - **Этап 2 (HTTP transport)** — закрыт шагом 05 (A2A-сервис на FastAPI).
> - **Этап 3 (Bearer auth)** — закрыт шагом 06 (`blocksnet_agent.authcore` + `a2a/auth.py`).
> - **Этап 4 (UrbanDB context adapter)** — закрыт шагом 06 (`blocksnet_agent.context` + `ScenarioContext`).
> - **Этап 5 (контракт v2)** — закрыт шагом 08 (`docs/tool_contract.md`, `docs/mcp_tool_catalog.md`).
> - **Этап 6 (Docker)** — закрыт шагом 07 (multi-stage, 2 образа, compose).
>
> **Осталось:** этапы 7-10 (MAS registry, e2e-тесты с реальным UrbanDB, reliability hardening, handoff).
> Подробный статус — в `docs/reports/a2a_refactor_completion_report.md`.

## Цель

К началу августа `blocksnet-mcp` должен быть интегрирован в MAS как сетевой MCP-сервис, который:

- доступен по HTTP / Streamable HTTP endpoint;
- защищён MAS-compatible Bearer/JWT-авторизацией;
- принимает MAS-контекст `scenario_id` / `project_id`;
- собирает данные из UrbanDB / Urban API в формат, совместимый с текущим `BlocksNetAgent`;
- возвращает стабильный структурированный JSON по контракту инструмента;
- запускается в контейнере и регистрируется в MAS / Urban services registry;
- покрыт smoke, integration и e2e-тестами.

Текущий локальный режим `stdio` должен сохраниться как dev/local fallback.

## Основной архитектурный принцип

Не переписывать `BlocksNetAgent` под MAS. Быстрее и безопаснее добавить платформенный слой:

```text
MAS / MCP client
  -> HTTP MCP endpoint
  -> auth middleware
  -> analyze_urban_question(question, scenario_id, project_id)
  -> UrbanDB context adapter
  -> temporary DATA_DIR compatible with BlocksNetAgent
  -> BlocksNetAgent.run(question)
  -> serialize.to_json(result)
  -> structured MCP response
```

Критичная часть — `UrbanDB context adapter`: он должен материализовать MAS-сценарий в файловую структуру, которую уже понимает агент.

---

## Сводная таблица этапов

| № | Этап | Оценка | Инженерные часы | Что можно передать ИИ | AI-часы | Критичность | Основной результат |
|---:|---|---:|---:|---|---:|---|---|
| 0 | Синхронизация MAS-контракта | 1–2 дня | 8–12 ч | Черновик вопросов к MAS-команде, шаблон assumptions/open questions, сверка docs | 2–4 ч | высокая | Зафиксированы transport, auth, формат вызова, UrbanDB API, требования регистрации |
| 1 | Разделение local core и MAS runtime | 2–3 дня | 12–18 ч | Рефактор settings, env matrix, CLI/runtime switch, обновление `.env.example`, unit-тесты | 6–10 ч | высокая | Сохранён `stdio`; добавлены режимы `local` / `mas`, runtime config, env-переменные |
| 2 | HTTP / Streamable HTTP MCP transport | 2–4 дня | 12–24 ч | Прототип HTTP entrypoint, health/readiness endpoints, smoke scripts, transport docs | 8–14 ч | высокая | Сетевой `/mcp`, `/health`, `/ready`, smoke через `curl` |
| 3 | Bearer/JWT auth | 2–3 дня | 12–18 ч | `auth.py`, negative/positive tests, error envelope, secret-handling docs | 8–12 ч | высокая | Авторизация endpoint, тесты 401/403/success, секреты только через env |
| 4 | UrbanDB context adapter | 5–7 дней | 30–42 ч | Скелет adapter/client, pydantic-схемы, mock UrbanDB fixtures, трансформация слоёв, validation tests | 12–20 ч | критическая | `scenario_id/project_id` превращаются во временный `DATA_DIR` для `BlocksNetAgent` |
| 5 | Контракт инструмента v2 для MAS | 2–3 дня | 12–18 ч | JSON schema, pydantic request/response models, contract tests, обновление `tool_contract.md` | 8–14 ч | высокая | Обновлены input/output schema, ошибки, docs, contract tests |
| 6 | Docker / deployment packaging | 3–4 дня | 18–24 ч | `Dockerfile`, `.dockerignore`, compose, env docs, smoke-команды; финальную проверку GDAL/GeoPandas делать человеком | 10–16 ч | высокая | `Dockerfile`, compose/dev запуск, healthcheck, контейнерный smoke |
| 7 | MAS registry / Urban services registration | 1–2 дня | 6–12 ч | Черновик registry metadata, service description, timeout/SLA таблица, registration docs | 4–8 ч | средняя | Готова регистрационная запись сервиса и metadata инструмента |
| 8 | Integration и e2e-тесты | 4–5 дней | 24–30 ч | Генерация pytest/smoke scripts, mock e2e harness, test report template, анализ логов падений | 14–22 ч | критическая | L0–L3 тесты: unit, local integration, staging UrbanDB, MAS e2e |
| 9 | Reliability hardening | 2–3 дня | 12–18 ч | Timeout wrappers, semaphore/queue skeleton, diagnostics, cache cleanup, failure classification tests | 8–14 ч | высокая | Таймауты, лимиты параллельности, cache, diagnostics, отказоустойчивость |
| 10 | Финальная документация и handoff | 2 дня | 12 ч | README/deployment/MAS docs, troubleshooting, финальный test report draft | 8–10 ч | средняя | README/deployment/tool contract/MAS docs/test report готовы к передаче |
| — | Буфер | 3–5 дней | 18–30 ч | Не планировать как AI-задачу: резерв на внешние блокеры, infra/auth/schema mismatch | — | обязательный | Резерв на UrbanDB schema mismatch, infra/auth surprises, performance issues |

Ориентир: **158–228 инженерных часов без буфера** или **176–258 часов с буфером**. Из них реалистично делегировать ИИ **88–144 часа** черновой инженерной работы: scaffold, тесты, документацию, smoke scripts, первичный анализ логов. Человеческая зона ответственности остаётся за MAS-контрактом, доступами, валидацией UrbanDB-семантики, финальными e2e и production-решениями.

### Как читать оценки human/AI

- **Инженерные часы** — суммарная оценка на этап с учётом ревью, ручной проверки и интеграции в реальную среду.
- **AI-часы** — объём работы, который можно отдать агенту как bounded coding/docs/test tasks. Это не полностью вычитается из инженерных часов: нужен review, запуск тестов и приёмка результата.
- **Не передавать ИИ без человека в контуре:** получение секретов, регистрация в MAS, подтверждение API UrbanDB, production deploy, окончательное решение по auth/security.
- **Лучший режим:** ИИ готовит patch + tests + smoke evidence; человек проверяет доменную корректность данных, доступы и интеграционный контур MAS.

---

## Этап 0. Синхронизация MAS-контракта — 1–2 дня

### Цель

Снять неопределённость до начала реализации. В текущей документации MAS помечен как Future, а локальные справки `docs/mas_integration_reference.md` и `docs/mas_registration.md` отсутствуют в рабочем дереве.

### Нужно зафиксировать

- Какой transport ожидает MAS:
  - Streamable HTTP MCP;
  - SSE;
  - REST wrapper поверх MCP.
- Какой auth используется:
  - static Bearer token;
  - JWT;
  - service-to-service token;
  - JWKS / issuer / audience, если применимо.
- Как MAS вызывает сервис:
  - прямой MCP tool call;
  - gateway call;
  - REST endpoint.
- Какие данные доступны через UrbanDB / Urban API:
  - `scenario_id`;
  - `project_id`;
  - blocks layer;
  - services layer;
  - population/demand;
  - accessibility matrix;
  - service taxonomy / aliases.
- Что нужно для регистрации в MAS:
  - service name;
  - endpoint URL;
  - healthcheck;
  - tool metadata;
  - timeout;
  - payload limits;
  - artifact policy.

### Deliverable

`docs/mas_integration_reference.md` или секция в этом плане с подтверждёнными assumptions и open questions.

---

## Этап 1. Разделение local core и MAS runtime — 2–3 дня

### Цель

Добавить платформенный runtime, не ломая текущий локальный `stdio` MVP.

### Работы

- Сохранить текущий `stdio` entrypoint.
- Добавить runtime modes:
  - `BLOCKSNET_MCP_MODE=local|mas`;
  - `MCP_TRANSPORT=stdio|http`;
  - `HOST`;
  - `PORT`;
  - `PUBLIC_BASE_URL`;
  - `AUTH_ENABLED`.
- Расширить `blocksnet_mcp/settings.py`:
  - network settings;
  - auth settings;
  - UrbanDB settings;
  - cache/output dirs.
- Разделить execution paths:
  - local: `DATA_DIR`;
  - MAS: `scenario_id/project_id -> context adapter -> temporary DATA_DIR`.

### Deliverable

- Local `stdio` продолжает работать.
- MAS config path готов к подключению HTTP/auth/context adapter.
- `.env.example` обновлён.

---

## Этап 2. HTTP / Streamable HTTP MCP transport — 2–4 дня

### Цель

Сделать `blocksnet-mcp` сетевым сервисом.

### Работы

- Проверить возможности текущего `mcp>=1.9.0` для HTTP / Streamable HTTP.
- Добавить HTTP entrypoint:
  - отдельный `blocksnet_mcp/http_server.py`, или
  - CLI/runtime switch в `server.py`.
- Поднять endpoints:
  - `/mcp`;
  - `/health`;
  - `/ready`.
- Добавить request logging:
  - request id;
  - scenario id;
  - project id;
  - run id;
  - duration;
  - status/failure reason.
- Добавить timeout defaults под долгий запуск агента.

### Deliverable

- Сервис запускается в HTTP mode.
- `tools/list` и `tools/call` проходят через network smoke.
- Health/readiness endpoints работают.

---

## Этап 3. Bearer/JWT auth — 2–3 дня

### Цель

Закрыть сетевой endpoint MAS-compatible авторизацией.

### Работы

- Добавить `blocksnet_mcp/auth.py`.
- Поддержать режимы:
  - `AUTH_ENABLED=false` для local/dev;
  - static Bearer token;
  - JWT/JWKS, если это требование MAS.
- Проверять `Authorization: Bearer ...`.
- Не логировать токены.
- Возвращать нормализованные ошибки:
  - `401 missing token`;
  - `403 invalid token`.
- Покрыть тестами:
  - no token;
  - invalid token;
  - valid token.

### Deliverable

Auth включается в MAS mode, тесты проходят, секреты остаются только в env.

---

## Этап 4. UrbanDB context adapter — 5–7 дней

### Цель

Поддержать MAS-вызов по `scenario_id/project_id` без переписывания `BlocksNetAgent`.

### Работы

- Расширить input tool contract:
  - `question`;
  - `scenario_id`;
  - `project_id`;
  - `max_iterations`;
  - optional: `city_id`, `territory_id`, `service_types`, если нужно MAS.
- Добавить `blocksnet_mcp/context.py` или `urban_context.py`.
- Реализовать UrbanDB client:
  - HTTP client;
  - retries/timeouts;
  - typed response validation.
- Материализовать данные в совместимый временный каталог:
  - `blocks_with_services.gpkg`;
  - `acc_mx.pickle`;
  - `service_type.json`;
  - `archetypes.csv`;
  - `platform/*.geojson`, если требуется текущими tools.
- Добавить валидацию перед запуском агента:
  - blocks есть;
  - population/demand есть;
  - services есть;
  - accessibility matrix есть;
  - CRS корректный;
  - service aliases разрешены.
- Добавить cache:
  - key: `scenario_id + project_id + data_version/hash`;
  - invalidation;
  - bypass для debugging.
- Нормализовать ошибки:
  - `DATA_UNAVAILABLE`;
  - `INVALID_SCENARIO`;
  - `UNSUPPORTED_SERVICE_LAYER`;
  - `ACCESS_MATRIX_MISSING`;
  - `URBANDB_TIMEOUT`.

### Deliverable

`analyze_urban_question(question, scenario_id, project_id)` запускает агент на данных UrbanDB, сохраняя local `DATA_DIR` mode.

---

## Этап 5. Контракт инструмента v2 для MAS — 2–3 дня

### Цель

Зафиксировать стабильный API для MAS.

### Работы

- Обновить `docs/tool_contract.md`.
- Добавить pydantic/schema-модели для request/response.
- Input v2:
  - `question`;
  - `scenario_id`;
  - `project_id`;
  - `max_iterations`;
  - optional filters.
- Output v2:
  - `status`;
  - `scenario_id`;
  - `project_id`;
  - `run_id`;
  - `analysis_plan`;
  - `result`;
  - `hypotheses`;
  - `measured`;
  - `recommendation_blocks`;
  - `confidence`;
  - `limitations`;
  - `warnings`;
  - `diagnostics`;
  - `artifacts`.
- Error envelope:
  - `status=error`;
  - `code`;
  - `message`;
  - `diagnostics`;
  - no raw traceback in MAS response.

### Deliverable

Contract docs, schema validation and tests готовы.

---

## Этап 6. Docker / deployment packaging — 3–4 дня

### Цель

Сделать сервис воспроизводимо запускаемым в MAS-инфраструктуре.

### Работы

- Добавить `Dockerfile`.
- Добавить `.dockerignore`.
- Добавить `docker-compose.yml` для local integration.
- Проверить system dependencies:
  - GDAL;
  - GEOS;
  - Fiona;
  - pyproj;
  - libspatialindex, если требуется;
  - зависимости BlocksNet/GeoPandas.
- Развести volumes:
  - `/app/outputs`;
  - `/app/cache`;
  - `/app/data` for local mode.
- Добавить env matrix:
  - `CHAT_URL`;
  - `API_KEY`;
  - `MODEL`;
  - `URBANDB_URL`;
  - `URBANDB_TOKEN`;
  - `MAS_BEARER_TOKEN` / JWT settings;
  - `OUTPUT_DIR`;
  - `CACHE_DIR`;
  - `MAX_ITERATIONS`.

### Deliverable

- `docker build` проходит.
- `docker run` поднимает `/health`.
- HTTP MCP smoke проходит внутри контейнера.

---

## Этап 7. MAS registry / Urban services registration — 1–2 дня

### Цель

Подготовить регистрационный пакет для MAS.

### Работы

- Подготовить metadata:
  - service name: `blocksnet-mcp`;
  - description;
  - endpoint URL;
  - protocol;
  - auth type;
  - timeout;
  - tool name;
  - input schema;
  - output schema;
  - tags/capabilities.
- Описать SLA/лимиты:
  - долгий вызов;
  - recommended timeout;
  - max payload;
  - expected artifacts.
- Сформировать `docs/mas_registration.md`.

### Deliverable

Готовая registry entry и smoke-call из MAS или MAS-like client.

---

## Этап 8. Integration и e2e-тесты — 4–5 дней

### Цель

Проверить реальный путь MAS -> service -> UrbanDB -> BlocksNetAgent -> JSON response.

### Уровни тестирования

| Уровень | Содержание | Цель |
|---|---|---|
| L0 unit | settings, auth, schemas, serializer, context transformation | Быстрая проверка логики без внешних сервисов |
| L1 local integration | local `DATA_DIR`, stdio, HTTP MCP, mocked UrbanDB | Проверка транспорта и контракта локально |
| L2 staging integration | real/staging UrbanDB, real scenario/project, Bearer auth, container | Проверка внешних зависимостей |
| L3 MAS e2e | MAS вызывает service, service тянет UrbanDB, агент считает, MAS получает JSON | Финальная проверка интеграции |

### Deliverable

- `pytest` suite.
- Smoke scripts:
  - `scripts/smoke_http_mcp.sh`;
  - `scripts/smoke_mas_context.py`;
  - `scripts/check_artifacts.py`.
- `docs/reports/mas_integration_test_report.md`.

---

## Этап 9. Reliability hardening — 2–3 дня

### Цель

Сделать поведение сервиса предсказуемым под ошибками и нагрузкой.

### Работы

- Timeouts:
  - agent timeout;
  - UrbanDB timeout;
  - MCP/http timeout.
- Ограничение параллельности:
  - semaphore/queue;
  - documented max concurrent runs.
- Cache materialized UrbanDB contexts.
- Log cleanup / retention.
- Failure classification:
  - recoverable;
  - fatal;
  - upstream unavailable;
  - invalid user/context input.
- Проверить большие сценарии:
  - memory;
  - runtime;
  - artifact size.

### Deliverable

Сервис не зависает бесконечно, диагностирует сбои и выдерживает ожидаемый профиль использования MAS.

---

## Этап 10. Финальная документация и handoff — 2 дня

### Цель

Передать MAS-команде готовый сервис с инструкциями запуска и диагностики.

### Документы

- `README.md`:
  - local stdio;
  - MAS HTTP mode;
  - Docker run.
- `docs/deployment.md`:
  - env;
  - ports;
  - auth;
  - healthcheck;
  - troubleshooting.
- `docs/tool_contract.md`:
  - v2 input/output;
  - error envelope.
- `docs/mas_integration_reference.md`:
  - architecture;
  - UrbanDB adapter;
  - assumptions;
  - limitations.
- `docs/mas_registration.md`:
  - registry values.
- `docs/reports/mas_integration_test_report.md`:
  - scenarios;
  - commands;
  - results;
  - blockers.

### Deliverable

Документация и evidence достаточны для регистрации, запуска и диагностики сервиса без автора рядом.

---

## Параллелизация

После этапа 0 можно вести четыре потока параллельно:

| Поток | Этапы | Комментарий |
|---|---|---|
| Transport/auth | 1, 2, 3 | Можно делать независимо от реального UrbanDB, используя mock context |
| UrbanDB data | 4 | Главный риск, начинать как можно раньше |
| Deployment | 6 | Можно стартовать после появления HTTP mode |
| Contract/docs/tests | 5, 7, 8, 10 | Должны обновляться вместе с реализацией |

---

## Минимальный MVP для августа

### Must-have

- HTTP MCP endpoint.
- Bearer/JWT auth.
- `scenario_id/project_id` в input.
- UrbanDB -> temporary `DATA_DIR` adapter.
- Docker image.
- MAS registry metadata.
- 1–2 e2e сценария.
- Structured JSON response.

### Should-have

- Cache invalidation by UrbanDB data version/hash.
- Rich diagnostics.
- Artifact publishing policy.
- Basic concurrency control.

### Can defer

- Дополнительные direct tools вроде `compute_service_provision`.
- Полноценная очередь задач.
- Advanced observability.
- Multi-city batch mode.
- Глубокая оптимизация TPE/performance.

---

## Критический путь

```text
MAS contract
  -> HTTP MCP endpoint
  -> auth
  -> UrbanDB context adapter
  -> tool contract v2
  -> Docker
  -> MAS registry
  -> staging e2e
  -> reliability hardening
```

Главный риск месячного плана — несовпадение формата UrbanDB/MAS данных с тем, что ожидает `BlocksNetAgent(data_dir=...)`. Поэтому UrbanDB adapter должен быть начат сразу после фиксации MAS-контракта, а не после завершения transport/auth.
