# Spike: a2a-sdk 1.1.1 — что подтверждено

Дата: 2026-07-21 (a2a/00)
Версия: `a2a-sdk==1.1.1` (актуальная стабильная на момент спайка).
Тестовая среда: `.venv-spike` (Python 3.11.15), изолированный venv.

## Версия и зависимости

- `a2a-sdk` 1.1.1 → дистрибутив называет себя `a2a-sdk`, но Python-пакет — `a2a` (не `a2a_sdk`).
- Прямые зависимости: `culsans`, `google-api-core`, `googleapis-common-protos`, `httpx`, `json-rpc`, `packaging`, `protobuf`, `pydantic`.
- Транзитивные через `httpx`: `sse_starlette`, `starlette`, `anyio`, `httpcore`, `h11` — нужны для SSE-роутов.
- Для юнит-тестов и in-process спайка нужны: `fastapi`, `pytest`, `starlette.testclient`. Запускать прод-сервер через `uvicorn`/`uvicorn-worker` — в этом окружении заблокировано (системный watcher), используем Starlette TestClient.

## Конфликты с основным venv

**Нет.** `--dry-run install a2a-sdk==1.1.1` в основном `.venv` показал, что все ключевые транзитивные
уже установлены (`httpx`, `pydantic`, `anyio`, `cryptography`, `wrapt`, `sniffio`).
Новые добавятся только: `aiologic`, `culsans`, `google-{api-core,auth,apis-common-protos}`,
`json-rpc`, `proto-plus`, `protobuf`, `pyasn1*`. Чисто.

## Архитектура (факт a2a-sdk 1.1.1, не доку)

- **JSON-RPC диспатчер** маршрутизирует по **именам gRPC методов**: `SendMessage`,
  `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `GetExtendedAgentCard`,
  `CreateTaskPushNotificationConfig`, `GetTaskPushNotificationConfig`,
  `ListTaskPushNotificationConfigs`, `DeleteTaskPushNotificationConfig`, `SubscribeToTask`.
  Это **НЕ** `message/send` (это имя из старой v0.3 спеки).
- **FastAPI точка входа**: `a2a.server.routes.fastapi_routes.add_a2a_routes_to_fastapi(app, ...)`.
  Три группы роутов: `agent_card_routes`, `jsonrpc_routes`, `rest_routes`.
- **Agent Card endpoint**: `/.well-known/agent-card.json` (по умолчанию, параметр `card_url`).
- **Версионирование**: handler ожидает header `A2A-Version: 1.0` (или `a2a-version`). Без
  header — фолбэк на `0.3` и `VersionNotSupportedError`. **Все клиенты должны слать `1.0`**.
- **Executor**: абстрактный класс `a2a.server.agent_execution.AgentExecutor` с двумя
  async-методами: `execute(context, event_queue)` и `cancel(context, event_queue)`.
- **Task store**: `InMemoryTaskStore` (для прод — `DatabaseTaskStore`, но это вне MVP).
- **Handler**: `DefaultRequestHandler` (он же `DefaultRequestHandlerV2`) — обязательный
  параметр `agent_card=...`.

## Формат сообщений (protobuf, не Pydantic!)

Все типы `a2a.types.*` — это **protobuf** (`a2a_pb2.*`), а не Pydantic-модели.
Это меняет подход к конструированию:

- `AgentCard` — НЕТ поля `url`. Вместо этого — repeated `supported_interfaces: AgentInterface`
  с полями `url`, `protocol_binding` (`"JSONRPC"` / `"GRPC"`), `protocol_version`, `tenant`.
- `Message.role` — enum `Role.ROLE_USER` (1) / `Role.ROLE_AGENT` (2) / `Role.ROLE_UNSPECIFIED` (0).
  В JSON через wire протокол — числом. **НЕ lowercase** (это была v0.3 Pydantic-схема, несовместима).
- `Message.parts` — repeated `Part`, где `Part` это **oneof**:
  `{text: string}` ИЛИ `{raw: bytes}` ИЛИ `{url: string}` ИЛИ `{data: DataPart}`.
  В JSON-сериализации — прямые поля без обёртки `kind`. В Pydantic-слое (старые версии)
  было `{"kind": "text", "text": "..."}` — это **НЕ работает** в 1.1.1.
- В HTTP-ответах JSON использует **camelCase** для ключей (`defaultInputModes`,
  `pushNotifications`, `supportedInterfaces`).

## Полный рабочий пример

`.venv-spike/spike_server.py` — минимальный end-to-end сервер:

- `StubExecutor` — echo входящего текста.
- `AgentCard` с одним skill `analyze_urban_question`.
- `DefaultRequestHandler(agent_executor, task_store, agent_card)`.
- `add_a2a_routes_to_fastapi(app, agent_card_routes, jsonrpc_routes)`.

Запрос:
```json
POST /
A2A-Version: 1.0
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "SendMessage",
  "params": {
    "message": {
      "role": 1,
      "parts": [{"text": "hello"}],
      "message_id": "m1"
    }
  }
}
```

Ответ:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {"message": {"role": "ROLE_AGENT", "parts": [{"text": "echo: hello"}]}}
}
```

## Зафиксировано в pyproject.toml

`a2a-sdk>=1.1.0` в extras `agent`. Сужение до точной версии `1.1.1` сделаем
после smoke на шаге 05, если упрёмся в регресс между минорными релизами.

## Ключевые отличия от документов в `../plan.md` / `../architecture.md`

- ❌ Старая спека A2A v0.3 использовала `message/send` как имя JSON-RPC метода.
  ✅ В a2a-sdk 1.1.1 это `SendMessage` (gRPC-style). Для шага 05 — учитывать.
- ❌ Старая спека использовала `{"kind": "text", "text": "..."}` для parts.
  ✅ В a2a-sdk 1.1.1 — `{"text": "..."}` напрямую (protobuf oneof).
- ❌ Старая спека использовала Pydantic-модели для AgentCard/Message.
  ✅ В a2a-sdk 1.1.1 — protobuf. `AgentCard.url` поля НЕТ — есть `supported_interfaces`.

## Exit-критерий шага 00.6

✅ Минимальный сервер поднимается, Agent Card валиден, `SendMessage` возвращает ответ.
Спайк успешен — можно строить шаг 05.