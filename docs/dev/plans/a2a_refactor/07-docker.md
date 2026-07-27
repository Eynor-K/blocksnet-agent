# Шаг 07 — Контейнеризация: два образа

**Цель.** `docker compose up` поднимает оба сервиса; MCP-образ не тянет
LLM-зависимости.

**Предусловия.** Шаги 03, 05, 06.

**Оценка.** 1 день.

---

## Задачи

### 7.1. `pyproject.toml` — довести extras

Заготовка сделана на шаге 00.5. Проверить фактическую разделимость:

```bash
python -m pip install -e ".[mcp]" --dry-run
python -c "import blocksnet_mcp.server"     # не должно тянуть langchain
```

Если `blocksnet_mcp` всё же тянет `langchain-core` — искать транзитивный
импорт. Ожидаемый источник: `blocksnet_agent/tools/*` импортируют
`langchain_core.tools`, а MCP строит каталог поверх `make_tools()`.

**Это ожидаемо и нормально**: `langchain-core` — лёгкий пакет с моделями
инструментов. Тяжёлые (`langchain-openai`, `langgraph`, `tiktoken`) в
MCP-образ попасть не должны. Зафиксировать в extras именно так:
`mcp` включает `langchain-core`, но не `langchain-openai`/`langgraph`.
Проверить тестом (7.5).

`requirements.txt` оставить как алиас для разработки:
`-e .[agent,dev]` — либо синхронизировать вручную и пометить комментарием.

### 7.2. `Dockerfile.mcp`

- multi-stage: builder (сборка колёс) + slim runtime;
- системные зависимости для `geopandas`/`blocksnet`: GDAL, GEOS, PROJ —
  без них образ не соберётся; проверить, что версии совпадают с теми, на
  которых работает локальный venv;
- `pip install .[mcp]`;
- non-root пользователь;
- `DATA_DIR`/`OUTPUT_DIR` — volume, не в образ;
- entrypoint `python -m blocksnet_mcp`;
- **LLM-переменные не объявлять** — это витрина того, что MCP их не требует.

### 7.3. `Dockerfile.agent`

То же + `.[agent]`, entrypoint `python -m blocksnet_agent`,
`EXPOSE ${A2A_PORT}`, `HEALTHCHECK` на `/health`.

### 7.4. `.dockerignore`

Обязательно исключить: `data/`, `outputs/`, `.venv*`, `examples/`,
`docs/`, `.git/`, `*.log`, `OptunaOptimizer.log`, `__pycache__`.
Каталог `data/` может весить гигабайты — без этого сборка встанет.

### 7.5. `docker-compose.yml`

- сервисы `agent` и `mcp`, общая сеть;
- общий volume на `DATA_DIR` (read-only для MCP, если материализация
  делается агентом) и на `OUTPUT_DIR`;
- `.env` через `env_file`;
- healthcheck: агент — HTTP `/health`; MCP по stdio так не проверить, поэтому
  либо запускать MCP в HTTP-режиме, либо healthcheck-командой
  `python -c "import blocksnet_mcp.server"`;
- лимиты памяти: агент ≥4 ГБ (GeoDataFrame + матрица доступности),
  MCP — по числу сессий (`MAX_SESSIONS` × размер данных).

### 7.6. `scripts/smoke_docker.sh`

`docker compose up -d` → ожидание healthcheck → Agent Card агента →
`tools/list` у MCP → `docker compose down`. Ненулевой код возврата при
любой ошибке.

### 7.7. Тест разделения зависимостей — `tests/test_image_deps.py`

```python
def test_mcp_package_does_not_import_heavy_llm_deps():
    """blocksnet_mcp.server не должен тянуть langgraph/langchain_openai/tiktoken."""
    subprocess.run([sys.executable, "-c",
        "import blocksnet_mcp.server, sys;"
        "assert not {'langgraph','langchain_openai','tiktoken'} & set(sys.modules)"],
        check=True)
```

Запускать в подпроцессе — иначе модули уже импортированы другими тестами.

---

## DoD

- [ ] `docker build -f Dockerfile.mcp .` и `-f Dockerfile.agent .` — успешны
- [ ] `docker compose up` — оба сервиса `healthy`
- [ ] `scripts/smoke_docker.sh` — код возврата 0
- [ ] MCP-контейнер стартует **без** `CHAT_URL`/`API_KEY` в окружении
- [ ] `python -m pytest tests/test_image_deps.py -q` — зелёный
- [ ] Размер MCP-образа меньше agent-образа (зафиксировать оба в
      `docs/deployment.md`)
- [ ] Коммит `a2a/07: two docker images and compose`

## Не делать

- Не копировать `data/` в образ.
- Не хардкодить токены/ключи в Dockerfile или compose.
- Не запускать контейнеры от root.
- Не делать `pip install -r requirements.txt` в MCP-образе — весь смысл
  шага в разделении зависимостей.

## Откат

Файлы сборки не влияют на код: удаление Dockerfile'ов, compose и
`.dockerignore` возвращает состояние после шага 06. `pyproject.toml`
оставить.
