# Регистрация `blocksnet-agent` в CodeSynapse

Документ для разработчика CodeSynapse (Synapse). Здесь всё, что нужно, чтобы
подключить сервис в свой тенант и получить успешный вызов, не обращаясь к
автору.

Проект даёт **два независимых канала**. Их можно подключать по отдельности:

| Канал | Что это | Приоритет |
|---|---|---|
| **A2A-агент** | городская аналитика целиком: вопрос → анализ → структурированный результат | основной |
| **MCP-сервер** | 33 инструмента для вашего собственного агента, без нашего LLM | опциональный |

Проверка соответствия контракту и известные ограничения:
[`reports/codesynapse_contract_compliance.md`](reports/codesynapse_contract_compliance.md).

---

## 1. A2A-агент

### 1.1 Значения для регистрации

Модель — `A2AServerConfigurationCreate`
(`src/schemas/configuration_schemas.py`). Готовый к вставке JSON:

```json
{
  "name": "blocksnet_urban",
  "endpoint_url": "https://<host>",
  "rpc_endpoint": "/",
  "request_timeout_seconds": 300,
  "enabled": true,
  "auth": { "type": "none" }
}
```

| Поле | Значение | Почему именно так |
|---|---|---|
| `name` | `blocksnet_urban` | уникально в тенанте; менять можно |
| `endpoint_url` | базовый URL сервиса | без пути; карточка ищется по `/.well-known/agent-card.json` |
| `rpc_endpoint` | **`/`** | **единственная строка, где легко ошибиться.** Наши JSON-RPC роуты смонтированы на корень (`create_jsonrpc_routes(handler, rpc_url="/")`), а ваш дефолт — `/a2a`. При дефолте вызов уйдёт на несуществующий путь |
| `agent_card_url` | не задавать | путь стандартный, поле нужно только для нестандартного |
| `request_timeout_seconds` | `300` | см. §1.4 — это ваш максимум, и он ниже нашего дедлайна |
| `auth` | по стенду | `none` для закрытого контура; иначе `bearer`/`api_key`/`oauth2` — см. §1.3 |

### 1.2 Что отдаёт карточка

Профиль **A2A 1.0** (полей 0.3 нет), `protocolVersion` строго `"1.0"`,
`protocolBinding` `JSONRPC`. Карточка проходит вашу
`synapse-a2a-1.0.schema.json` с нулём расхождений — проверяется нашим тестом
`tests/test_codesynapse_contract.py` на каждом прогоне.

- `defaultInputModes`: `text/plain`
- `defaultOutputModes`: `text/plain`, `application/json`
- `capabilities`: `streaming: true`, `pushNotifications: false`
- skills: `run_pipeline` (основной), `analyze_urban_question` (DEPRECATED)

**Required Profile Extension** —
`https://blocksnet.itmo.ru/extensions/urban-task-input/v1`. Именно он включает
ваше извлечение параметров (`required_extensions_with_schema` →
forced-tool LLM-вызов → DataPart). Схема параметров:

| Параметр | Тип | Ограничение | Смысл |
|---|---|---|---|
| `scenario_id` | string | `^[a-zA-Z0-9_-]{1,64}$` | сценарий, к данным которого относится вопрос |
| `project_id` | string | `^[a-zA-Z0-9_-]{1,64}$` | проект MAS, к которому относится прогон |
| `max_iterations` | integer | 1..100 | лимит итераций агента |

Обязательных параметров **нет** осознанно: без `scenario_id` анализ идёт на
датасете по умолчанию. Если вам нужно, чтобы прогон без сценария падал до
обращения к нам, скажите — это одна строка в нашей схеме (`required`).

> **Важно про `scenario_id`.** UrbanDB к сервису **не подключён** и подключаться
> пока не будет: blocksnet работает на специфично подготовленных данных, которых
> UrbanDB не отдаёт. Поэтому `scenario_id` — это **имя заранее подготовленного
> датасета**, смонтированного на инстанс (`DATA_DIR/<scenario_id>`), а не
> идентификатор сценария в вашей системе. Передавать сюда ваш внутренний
> scenario id **не нужно** — он не разрешится. См. §1.7.

### 1.3 Авторизация

Сервис поддерживает bearer-токен (`blocksnet_agent/a2a/auth.py`,
`A2A_AUTH_ENABLED` / `A2A_BEARER_TOKEN`). Значения передаются отдельно от этого
документа — здесь только имена переменных.

### 1.4 Таймауты — согласовать до первого прогона

| Сторона | Параметр | Значение |
|---|---|---|
| CodeSynapse | `request_timeout_seconds` | 1..300, дефолт 60 |
| blocksnet-agent | `DEADLINE_SEC` | по умолчанию **480** |

Полный прогон агента идёт минуты, поэтому дефолтные 60 секунд почти наверняка
оборвут вызов, и снаружи это будет выглядеть как наш отказ. Рекомендация:
поставить `request_timeout_seconds: 300` и на нашей стороне `DEADLINE_SEC=280`,
чтобы дедлайн срабатывал **у нас** и вы получали внятный
`TASK_STATE_FAILED`, а не разрыв соединения. Реальное время прогона на вашем
датасете пока не измерено — см. открытый вопрос №3 в отчёте о соответствии.

### 1.5 Что вы получите в ответ

Ответ — **Task** (не сообщение), валидный по вашему `$defs.task`:

- `status.state`: `TASK_STATE_COMPLETED` / `TASK_STATE_FAILED` /
  `TASK_STATE_CANCELED`;
- `status.message` — причина отказа в виде `ERROR_CODE: текст`, без traceback
  (ваш `a2a_delegate` показывает именно её);
- `artifacts[0]` — `analysis-result`: `data`-часть со структурированным
  результатом и `text`-часть со сводкой;
- далее — по артефакту на текстовый/табличный файл прогона (до 256 KB).

Растровые карты **не встраиваются**: они перечислены в
`analysis-result.data.skipped_artifacts` с причиной. Если они вам нужны — см.
открытый вопрос №2.

### 1.6 Предусловия развёртывания — прочитать до регистрации

Сервис не «самодостаточен»: он анализирует данные, которые ему заранее
положили. Без этого он зарегистрируется и будет отвечать, но каждый вызов
завершится отказом.

| Что нужно | Зачем | Без этого |
|---|---|---|
| Датасет города на volume (`DATA_DIR`) | исходные данные blocksnet: `blocks_with_services.gpkg`, `acc_mx.pickle` и др. | любой прогон падает |
| LLM-эндпоинт (`CHAT_URL`, `API_KEY`, `MODEL`) | A2A-агент рассуждает через OpenAI-совместимый API | сервис не стартует осмысленно |
| `OUTPUT_DIR` на записываемом volume | артефакты прогона | прогон падает на записи |

Датасеты в репозитории не лежат (СПб — 336 MB) и готовятся отдельно.
MCP-серверу LLM не нужен — только данные.

### 1.7 Как адресуются датасеты

- **Один датасет на инстанс** — самый простой режим: смонтировать его в
  `DATA_DIR`, `scenario_id` не передавать вовсе.
- **Несколько датасетов** — разложить по подкаталогам `DATA_DIR/<имя>` и
  передавать имя как `scenario_id` (`saint_petersburg`, `kronstadt`, …).

Если `scenario_id` не соответствует подготовленному датасету, вы получите
**штатный** отказ, а не аварию:

```
TASK_STATE_FAILED
SCENARIO_NOT_MATERIALIZED: scenario 'spb-772' is not provisioned;
available scenarios: kronstadt, saint_petersburg
```

Список доступных датасетов в сообщении — чтобы ваш агент мог исправиться сам,
не обращаясь к нам. Абсолютные пути нашей ФС наружу не отдаются.

Обратите внимание: ваше извлечение параметров — это LLM по нашей схеме, и в
описании параметра прямо сказано не выводить значение из топонимов в тексте.
Если вопрос звучит «где в Кронштадте разместить площадки», значение
`scenario_id` извлекаться **не должно** — иначе оно почти наверняка не совпадёт
с именем датасета. Проверьте это на первом же прогоне.

### 1.8 Проверка перед регистрацией

```bash
# карточка против вашей же схемы
python scripts/validate_agent_card.py --url https://<host>
```

---

## 2. MCP-сервер

### 2.1 Канал поставки: `stdio` + Docker Image

| Канал | Решение | Почему |
|---|---|---|
| **`docker/stdio`** | **выбран** | наш образ уже stdio (`ENTRYPOINT ["python","-m","blocksnet_mcp"]`), а поле Docker Image в вашем Discover UI доступно **только** для stdio (`mcp-server-templates/README.md`, §«Docker HTTP в UI») |
| `zip/stdio`, `zip/streamable-http` | отвергнут | ZIP собирает образ на хосте вашего API. Зависимости тяжёлые (geopandas, optuna, matplotlib, blocksnet) — минуты сборки и реальный риск `build_failed`; плюс нужна роль tenant admin |
| `remote/streamable-http`, `remote/http` | резерв | требует переписать entrypoint (сейчас `mcp.run(transport="stdio")` жёстко, порт не публикуется) и публичный DNS: ваш SSRF-фильтр отклоняет `localhost`/private IP (`endpoint host is not allowed`) |
| `docker/http`, `docker/streamable-http` | отвергнут | те же доработки, что и remote, без выигрыша перед stdio |

### 2.2 Поля Discover

| Поле | Значение |
|---|---|
| Server ID | `blocksnet` (без точек и пробелов; public id инструментов — `blocksnet.<tool>`) |
| Connection Type | **STDIO** |
| Docker Image | тег из вашего registry (см. §2.3) |
| Timeout | 1..300 сек; рекомендуем 120 |
| Env vars контейнера | `DATA_DIR`, `OUTPUT_DIR` — если данные монтируются; LLM-переменные **не нужны** |

LLM-стек в MCP-контейнер не входит (extras `mcp` без langchain/a2a), поэтому
`CHAT_URL`/`API_KEY` у нас не спрашивайте — они нужны только A2A-агенту.

### 2.3 Образ

Собирается из репозитория:

```bash
docker build -f Dockerfile.mcp -t blocksnet-mcp:local .
python scripts/smoke_mcp_docker.py --image blocksnet-mcp:local
```

Для вашего стенда образ должен быть доступен docker-демону **хоста вашего
API**: локальный тег не разрешится. Registry, тег и credentials согласуются
отдельно. Собирайте под целевую платформу явно (`--platform linux/amd64`),
иначе `docker run` упадёт неочевидно.

### 2.4 Инструменты и сессии

33 каталожных инструмента + 3 сессионных (`open_session`, `close_session`,
`session_info`). Все принимают первым аргументом `session_id`.

Важное про жизненный цикл: ваш исполнитель кэширует stdio-контейнер по ключу
`(project_id, tenant_id, server_id)` и закрывает его при финализации проекта.
Значит состояние сессии живёт **в пределах проекта**: `load_blocks` переживёт
цепочку вызовов, а следующий проект получит пустое состояние. Инструменты,
читающие состояние, отвечают структурной ошибкой с подсказкой о следующем
шаге — ваш агент может исправиться сам.

Полный каталог: [`mcp_tool_catalog.md`](mcp_tool_catalog.md).

---

## 3. Процедура: от нуля до успешного вызова

Шаги проверены на чистой машине. Каждый копируется целиком; после каждого
указано, что должно быть видно.

### Сценарий A — A2A локально (15 минут, без вашего стенда)

```bash
git clone <repo> && cd blocksnet-agent
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[agent,dev]"

cp .env.example .env          # заполнить CHAT_URL, API_KEY, MODEL
python -m blocksnet_agent      # поднимает A2A на :8080
```

Проверка карточки — вашей же схемой:

```bash
python scripts/validate_agent_card.py --url http://127.0.0.1:8080
# OK: Agent Card валидна по A2A 1.0 ... skills=[run_pipeline, analyze_urban_question]
```

Вызов (обратите внимание на заголовок версии — без него SDK считает запрос 0.3):

```bash
curl -sS http://127.0.0.1:8080/ \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{
        "messageId":"m1","role":"ROLE_USER",
        "parts":[{"text":"Где в Кронштадте разместить спортплощадки?"},
                 {"data":{"scenario_id":"spb-1"}}]}}}'
```

Ожидаемо: `result.task.status.state` = `TASK_STATE_COMPLETED`, в
`result.task.artifacts[0]` — `analysis-result` с `data`- и `text`-частями.

### Сценарий B — A2A в вашем тенанте

1. Развернуть сервис так, чтобы он был доступен вашему API-хосту.
2. Зарегистрировать по значениям из §1.1 — **`rpc_endpoint` = `/`**.
3. `POST /a2a-configurations/{id}/validate` — карточка должна пройти.
4. Вызвать нодой `a2a_agent` или делегированием.

### Сценарий C — MCP

```bash
docker build -f Dockerfile.mcp -t blocksnet-mcp:local .
python scripts/smoke_mcp_docker.py --image blocksnet-mcp:local
# OK: образ пригоден для регистрации в CodeSynapse (mode stdio)
```

Затем: залить образ в registry, доступный вашему API-хосту (§2.3) →
MCP Tools → Discover → Docker → mode **stdio** → Image → Import Selected.

---

## 3. Если не работает

| Симптом | Причина | Что делать |
|---|---|---|
| JSON-RPC 404 / метод не доходит | `rpc_endpoint` оставлен дефолтным `/a2a` | поставить `/` (§1.1) |
| `a2a_output_modes_unsupported` при регистрации | карточка объявила режимы, которые вы не понимаете | наши режимы — `text/plain` и `application/json`, оба поддержаны; проверьте, что забрали свежую карточку |
| `a2a_protocol_version_unsupported` | ожидался строго `"1.0"` | у нас `"1.0"`; проверьте, что не подмешался кэш карточки 0.3 |
| Карточка валидна, но `scenario_id` не доехал | расширение не активировано | проверьте заголовок `A2A-Extensions` и `required: true` у расширения в карточке |
| `endpoint host is not allowed` | SSRF-фильтр на MCP Discover | публичный DNS, `EXTERNAL_MCP_ENDPOINT_ALLOWLIST` или `EXTERNAL_MCP_ALLOW_LOCAL_ENDPOINTS=true` (lab) |
| Вызов обрывается по таймауту | `request_timeout_seconds` меньше времени прогона | §1.4 |
| MCP: образ не найден | указан локальный тег | образ должен быть доступен демону вашего API-хоста (§2.3) |
