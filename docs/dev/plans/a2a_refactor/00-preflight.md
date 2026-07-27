# Шаг 00 — Подготовка: окружение, baseline, спайк a2a-sdk

**Цель.** Иметь воспроизводимое окружение, зафиксированный baseline тестов и
проверенную версию `a2a-sdk` — до того, как что-то менять.

**Предусловия.** Чистый рабочий каталог (`git status` без незакоммиченных
изменений в `blocksnet_agent/`, `blocksnet_mcp/`, `tests/`). Ветка
`feat/a2a-refactor` от `main`.

**Оценка.** 0.5 дня.

---

## Задачи

### 0.1. Окружение

В текущем окружении Python-зависимостей нет (`import mcp` →
`ModuleNotFoundError`, `pip` отсутствует). Поднять venv:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m ensurepip --upgrade || curl -sS https://bootstrap.pypa.io/get-pip.py | python
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Если `blocksnet>=1.0.0a9` или `geopandas` не ставятся (нужны системные
библиотеки GDAL/GEOS) — зафиксировать это в `deviations.md` и продолжать:
шаги 01–03 и 05 не требуют реального `blocksnet`, тесты работают на моках.
Проверить минимум: `python -c "import mcp, langchain_core, pydantic; print('ok')"`.

### 0.2. Baseline тестов

```bash
python -m pytest -q 2>&1 | tee docs/a2a_refactor/implementation/baseline.txt
```

Записать в конец файла дату и краткий вывод. Этот файл — эталон: на каждом
следующем шаге набор упавших тестов не должен расширяться.

Если часть тестов красная **уже сейчас** — не чинить, зафиксировать как
известное состояние (в baseline и в `deviations.md`).

### 0.3. Инвентаризация инструментов (снимок факта)

Нужен, чтобы шаг 01 не строился на догадках:

```bash
grep -rn "^\s*@tool" -A3 blocksnet_agent/tools/*.py | grep "def " \
  > docs/a2a_refactor/implementation/tools_snapshot.txt
```

Ожидаемо (сверено 2026-07-21): data 9, network 6, services 6, indicators 3,
optimize 3, provision 2, viz 1 = 30 доменных; `registry.py` — `find_tools`,
`get_tool_help`; плюс `submit_answer`, добавляемый динамически в
`make_tools()`. Итого 33 в наборе агента, 32 к экспозиции.

Если фактические числа отличаются — обновить их в
[../../decisions/reasoning.md](../../decisions/reasoning.md) §1 и продолжать. Числа в коде и тестах
не хардкодить (инвариант 7).

### 0.4. Проверка потребителей `analyze_urban_question`

Убедиться, что список из [../../decisions/review.md](../../decisions/review.md) R8 актуален:

```bash
grep -rn "analyze_urban_question" --include=*.py . | grep -v "^./docs"
```

Ожидаемые 6 мест: `blocksnet_mcp/__init__.py`, `tests/test_tool_contract.py`,
`tests/test_async_mcp_contract.py`, `scripts/smoke_client.py`,
`examples/_lib/run_mcp.py`, `examples/city_picker.py`. Появившиеся новые —
дописать в шаг [03](03-mcp-server.md), задача 3.7.

### 0.5. Заготовка pyproject.toml

Создать `pyproject.toml` с extras — понадобится на шаге 07, но объявить
границы зависимостей нужно сейчас, пока они ещё не перемешались:

- `[project.optional-dependencies].mcp` — `mcp`, `pydantic-settings`,
  `python-dotenv`, `geopandas`, `pandas`, `numpy`, `blocksnet`, `matplotlib`,
  `optuna`
- `.agent` — всё из `mcp` + `langchain-core`, `langchain-classic`,
  `langchain-openai`, `langgraph`, `tiktoken`, `a2a-sdk`
- `.dev` — `pytest`, notebook-зависимости

`requirements.txt` пока оставить как есть (на него завязаны примеры);
синхронизация — на шаге 07.

### 0.6. Спайк `a2a-sdk` (блокирующий для шага 05)

Делать **сейчас**, а не перед шагом 05: результат может изменить объём.

1. Найти актуальную версию: `python -m pip index versions a2a-sdk`
   (или `pip download a2a-sdk --no-deps -d /tmp/a2a`).
2. Установить в **отдельный** venv (`.venv-spike`), не в основной — SDK может
   конфликтовать по `pydantic`/`httpx`. Проверить конфликт явно:
   `python -m pip install a2a-sdk -c <(python -m pip freeze)` в основном venv
   в режиме `--dry-run`.
3. Воспроизвести минимальный сервер из README SDK:
   - поднимается,
   - `GET /.well-known/agent-card.json` (или путь, который использует
     текущая версия SDK — зафиксировать фактический) отдаёт валидный Agent Card,
   - `message/send` возвращает ответ.
4. Записать в `docs/a2a_refactor/implementation/spike-a2a.md`: точную версию,
   фактический путь Agent Card, имена классов сервера/executor, ссылку на
   пример, конфликты зависимостей.
5. Запинить в `pyproject.toml`: `a2a-sdk==<точная версия>`.

**Ссылка на спеку:** канонический репозиторий — `https://github.com/a2aproject/A2A`
(ранее `google/A2A`; ссылка `a2a-protocol/a2a-spec` из первой редакции
документов не проверена). Уточнить при спайке и исправить в
[../../decisions/open_questions.md](../../decisions/open_questions.md) Q1, если не совпало.

**Exit-критерий.** Пункт 3 воспроизведён. Если нет — не изобретать обходные
пути: зафиксировать в `deviations.md` и эскалировать (альтернатива —
собственный JSON-RPC, вариант B в Q1, +3–5 дней).

---

## Тесты

Новых нет. Шаг только фиксирует состояние.

## DoD

- [ ] `. .venv/bin/activate && python -c "import mcp, langchain_core"` — без ошибок
- [ ] `baseline.txt` существует и содержит вывод pytest
- [ ] `tools_snapshot.txt` существует; число инструментов сверено с §1 reasoning
- [ ] `spike-a2a.md` существует, версия `a2a-sdk` зафиксирована в `pyproject.toml`
- [ ] `pyproject.toml` создан с тремя extras
- [ ] Коммит `a2a/00: preflight — env, baseline, a2a-sdk spike`

## Не делать

- Не менять `requirements.txt` под `a2a-sdk` — MCP-образ не должен его тянуть.
- Не чинить красные тесты из baseline «заодно» — это скроет регресс на
  следующих шагах.
- Не ставить `a2a-sdk` в основной venv до шага 05.

## Откат

`git checkout -- pyproject.toml && rm -rf .venv-spike`. Артефакты
(`baseline.txt`, `tools_snapshot.txt`, `spike-a2a.md`) сохранить в любом случае.
