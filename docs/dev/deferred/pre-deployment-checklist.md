# Pre-Deployment Checklist

**Не задачи, а обязательный чеклист перед любым развертыванием (Docker, MAS, dev).**

Возник из ревизии 22.07.2026: тесты в локальной песочнице зелёные (257 passed,
агент отвечает за 181 сек через 5 tool-calls), но это **не означает готовность к
развертке**. Ниже — что нужно проверить вручную.

---

## Блокер #1: Docker-сборка ни разу не запускалась

В этой песочнице `docker` отсутствует. `Dockerfile.mcp`, `Dockerfile.agent`,
`docker-compose.yml` написаны на шаге 07, но **никогда не собирались**.

**Риски:**
- Версия `libgdal34t64` есть только в Ubuntu 24.04; на 22.04 и ниже — fail.
- `a2a-sdk` указан в `pyproject.toml` (`agent` extras), но не проверено, что
  `pip install .[agent]` действительно его подтянет (зависимость новая, добавлена
  на шаге 00).
- Healthcheck через `curl` работает только в `python:3.11-slim` — проверено
  только теоретически.

**Что делать (10–20 мин):**

```bash
docker compose build
docker compose up -d
docker compose ps          # оба сервиса должны быть healthy
docker compose logs agent  # нет ошибок при старте
docker compose logs mcp    # нет ошибок при старте
```

**Если сборка падает** — правьте `Dockerfile.mcp`/`Dockerfile.agent` или
`pyproject.toml`. Это **блокирующий пункт**.

---

## Блокер #2: реальный клиент не подключался

Все мои тесты — `TestClient` (starlette in-process) и прямые вызовы через
`.venv/bin/python`. Реальный MCP-клиент (Claude Desktop, Cursor) или реальный
A2A-клиент (curl с правильными headers) — не подключались.

**Особенности a2a-sdk 1.1.1, которые нужно проверить:**

1. Header `A2A-Version: 1.0` **обязателен** (без него — `VersionNotSupportedError`).
2. Поле `role` в `Message` — это **enum**, в wire JSON ожидается **число**
   (`ROLE_USER = 1`, `ROLE_AGENT = 2`), не строка `"user"`.
3. JSON-RPC метод: `SendMessage` (PascalCase, gRPC-style), не `message/send`.

**Что делать (5–10 мин):**

```bash
# A2A через curl с правильным header:
curl -X POST http://localhost:8080/ \
  -H "A2A-Version: 1.0" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "SendMessage",
    "params": {
      "message": {
        "role": 1,
        "parts": [{"text": "Какие сервисы есть?"}],
        "messageId": "test-msg-1"
      }
    }
  }'

# MCP через stdio — настроить Claude Desktop / Cursor,
# указать python -m blocksnet_mcp как MCP-server.
```

**Если клиент получает 401 / 400 / `VersionNotSupportedError`** — это блокирующая
ошибка интеграции, не теста.

---

## Блокер #3: полный прогон с `MAX_ITERATIONS=10` не делался

В тестах я использовал `max_iterations=2` (99 сек) и `max_iterations=4` (181 сек).
С дефолтным `MAX_ITERATIONS=10` в `.env` прогон может длиться **5–10 минут**
(плюс TPE-оптимизация `compute_scenario_provision` и сохранение карт).

**Риски:**
- `DEADLINE_SEC=480` (8 минут) в `.env` может быть недостаточно для полного
  прогона — будет `status="partial"` (легитимный результат, но не полный).
- Долгие вызовы могут быть прерваны MCP-клиентом (таймаут на стороне клиента).

**Что делать (10 мин):**

```bash
DATA_DIR=data/saint_petersburg .venv/bin/python -c "
import sys, time
sys.path.insert(0, '.')
from blocksnet_mcp.tools_mcp import analyze_urban_question
start = time.time()
result = analyze_urban_question(
    'Какие кварталы имеют наименьшее покрытие школами? Где разместить новые?',
    max_iterations=10,
)
print(f'Elapsed: {time.time() - start:.1f}s')
print(result[:500])
"
```

**Если elapsed > 480 сек** — либо поднять `DEADLINE_SEC`, либо принять, что
полный прогон будет partial.

---

## Блокер #4: боевые ключи в `.env`

`.env` содержит реальный Ollama Cloud API-ключ (57 символов).

**Риски:**
- Если `.env` случайно закоммитится — компрометация ключа, нужно ротировать.
- Если ключ попадёт в логи контейнера — то же самое.
- В логах `A2A auth failed: ... code=invalid_token` **не содержит токен** (это
  проверялось в `tests/test_auth.py`), но Docker-логи могут утечь через volume.

**Что делать (1 мин):**

```bash
git status --ignored    # убедиться, что .env НЕ в git
cat .gitignore | grep -E '^\.env'
cat .dockerignore | grep -E '^\.env'
```

В обоих файлах `.env` должно быть. Если нет — **добавить до развертки**.

**Если ключ уже был закоммичен** — ротировать его в Ollama Cloud dashboard.

---

## Блокер #5: параллельная нагрузка не проверялась

В тестах я запускал **один** запрос. Что будет при 5 параллельных:

- `TaskManager` имеет лимит `A2A_MAX_CONCURRENT_TASKS=2` (default) — остальные
  ждут в `submitted`.
- `SessionStore` имеет лимит `MAX_SESSIONS=8` (default) — девятая сессия вытеснит
  первую через LRU.
- `submit_answer` терминальный — при одновременном завершении N задач возможна
  гонка за `RunLogger` (нужно проверить thread-safety).

**Что делать (опционально, 15 мин):**

```bash
# Запустить 5 параллельных запросов:
for i in 1 2 3 4 5; do
  DATA_DIR=data/saint_petersburg .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from blocksnet_mcp.tools_mcp import analyze_urban_question
import time; start = time.time()
result = analyze_urban_question('Вопрос $i', max_iterations=2)
print(f'$i: {time.time() - start:.1f}s, len={len(result)}')
" &
done
wait
```

**Если есть таймауты или потерянные ответы** — увеличить `MAX_SESSIONS` или
`A2A_MAX_CONCURRENT_TASKS`.

---

## Блокер #6: нет CI для pre-flight проверок

Docker-сборка, smoke-тесты, линтинг — всё запускалось вручную. Для регулярных
развертываний нужен CI.

**Что делать (если есть CI):**

- ✅ Добавлен `.github/workflows/pre-deployment.yml` — три job:
  - `pytest` — 257 тестов на Python 3.11
  - `docker-mcp` — сборка `Dockerfile.mcp`
  - `docker-agent` — сборка `Dockerfile.agent`
  - `smoke` — `docker compose up -d` + проверка `/health` + Agent Card
- Запускается на push/PR в main и feat/a2a-refactor, можно вручную через
  `workflow_dispatch` (Actions → pre-deployment → Run workflow).

**Если CI нет** — workflow готов к использованию как есть.

---

## Итоговый чеклист (распечатать и пройти)

Результат прогона 22.07.2026 (см. `docs/reports/a2a_pre_deployment_checklist_run.md`):

```
[x] 1. .env НЕ в git (git status --ignored; cat .gitignore | grep .env)
[x] 2. .env НЕ в Docker-образе (cat .dockerignore | grep .env)
[x] 3. docker compose build — успех (оба образа: mcp 473MB, agent 495MB)
[ ] 4. docker compose up -d — оба сервиса healthy (docker compose ps)
    ⚠️ НЕ ПРОВЕРЕНО в этой песочнице (sysctl restriction в nested Docker).
    Проверить на реальной машине.
[x] 5. curl http://localhost:8080/health — 200 (проверено через TestClient)
[x] 6. curl http://localhost:8080/.well-known/agent-card.json — JSON с 2 skill
[x] 7. A2A SendMessage без A2A-Version: 1.0 → VersionNotSupportedError (контракт верен)
[ ] 8. MCP через stdio — клиент видит 32 tools (проверено через прямой call, не через клиент)
[ ] 9. Реальный вопрос агенту — 10 tool-calls, submit_answer достигнут (194.6 сек)
[x] 10. Прогон с MAX_ITERATIONS=10 — 194.6 сек < DEADLINE_SEC=480
[x] 11. (опц.) 5 параллельных запросов — 5/5 успешны, 214-438 сек каждый
[x] 12. (опц.) CI job docker-build — workflow готов (`.github/workflows/pre-deployment.yml`)
```

---

## Когда блокирующие пункты закрыты

| Пункт | После | Действие |
|---|---|---|
| Блокер #1 (Docker) | `docker compose build` зелёный | `git tag v0.2.0-rc1` |
| Блокер #2 (клиент) | curl-тест прошёл, MCP-клиент видит tools | `git tag v0.2.0-rc2` |
| Блокер #4 (.env) | `.gitignore` и `.dockerignore` проверены | — |
| Все галочки в чеклисте | ✅ | `git tag v0.2.0` — готово к продакшну |

---

## Связь с другими документами

- [../deferred/a2a_refactor_deferred.md](a2a_refactor_deferred.md) — D1-D6: что
  НЕ делаем в этой итерации (MCP_TOOL_PROXY, JWT, structured output, push).
- [../plans/mas_integration.md](../plans/mas_integration.md) — этапы 7-10 MAS-плана
  (HTTP MCP endpoint, JWT, UrbanDB integration, e2e-тесты, hardening, handoff).
- [../../deployment.md](../../deployment.md) — Quickstart, env-таблица,
  troubleshooting (уже есть в основной документации).