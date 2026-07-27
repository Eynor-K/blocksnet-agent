# Шаг 01 — Каталог инструментов: общая точка правды

**Цель.** Один вызов, дающий описанный набор инструментов, — чтобы и агент,
и MCP-сервер строили каталог из одного места и не расходились.

**Предусловия.** Шаг 00 завершён, `tools_snapshot.txt` на руках.

**Оценка.** 0.5 дня.

---

## Контекст, без которого шаг будет сделан неверно

`blocksnet_agent/tools/registry.py` **уже существует** (151 строка) и делает
совсем другое: двухуровневые docstring'и (короткое описание в `.description`,
полное — в реестр), RAG-инструменты `find_tools`/`get_tool_help`, индекс
синонимов сервисов. **Его не трогаем.** Новый модуль — `catalog.py`.

Инструменты создаются фабрикой:

```python
make_tools(state: dict, data_dir: Path, output_dir: Path) -> list[BaseTool]
```

Внутри: композиция `make_*_tools(ctx)` → `_build_submit_answer_tool(state)` →
`build_tool_registry()` (короткие описания) → `make_help_tools()` →
`_memoize_tools()` (кэш + streak-лимит RAG). Порядок важен, менять нельзя.

Каталог обязан строиться **из живых объектов** `BaseTool`, а не из импорта
функций поштучно: `find_tools`/`get_tool_help` вообще не существуют вне
`make_help_tools(registry)`.

---

## Задачи

### 1.1. `blocksnet_agent/tools/catalog.py` — новый файл

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

# Инструменты, которые не экспонируются наружу (только агентский цикл).
# submit_answer — терминальный: пишет state["_submitted_answer"] и завершает PTR.
TOOL_BLOCKLIST: frozenset[str] = frozenset({"submit_answer"})


@dataclass(frozen=True)
class ToolSpec:
    """Описание одного инструмента для внешней экспозиции."""

    name: str
    short: str          # первая строка docstring (то же, что видит LLM)
    full: str           # полная справка из реестра
    args_schema: dict[str, Any]   # JSON Schema входа
    tool: BaseTool      # живой объект для вызова


def build_catalog(
    state: dict,
    data_dir: Path,
    output_dir: Path,
    *,
    include_blocked: bool = False,
) -> list[ToolSpec]:
    """Строит каталог инструментов поверх make_tools().

    Единственная точка, из которой MCP-сервер узнаёт, что экспонировать.
    Агент продолжает пользоваться make_tools() напрямую — каталог ему не нужен.
    """
```

Требования к реализации:

- вызывает `make_tools(state, data_dir, output_dir)`, ничего в ней не меняя;
- `short` берёт из `tool.description` (там уже короткое описание после
  `build_tool_registry`), `full` — из `tool.description` fallback'ом, если
  полной справки нет;
- `args_schema` — из `tool.args_schema.model_json_schema()` с fallback на
  `{"type": "object", "properties": {}}` при ошибке;
- фильтрует по `TOOL_BLOCKLIST`, если `include_blocked=False`;
- **не кэширует** результат глобально: каталог привязан к `state`.

### 1.2. Доступ к полной справке

`build_tool_registry()` возвращает `(short_tools, registry)`, но
`make_tools()` реестр наружу не отдаёт. Варианты, в порядке предпочтения:

**A (предпочтительно).** Добавить в `make_tools()` необязательный
out-параметр, не меняя сигнатуру для существующих вызывающих:

```python
def make_tools(state, data_dir, output_dir, *, registry_out: dict | None = None):
    ...
    short_tools, registry = build_tool_registry(domain_tools)
    if registry_out is not None:
        registry_out.update(registry)
    ...
```

Существующий вызов `agent.py:116` (`make_tools(self._state, ...)`)
продолжает работать без изменений — правка `agent.py` не требуется.

**B (запасной).** В `catalog.py` дёрнуть `get_tool_help(name)` из набора и
распарсить ответ. Работает, но хрупко — только если A по какой-то причине
невозможен.

### 1.3. Хелперы каталога

```python
def catalog_names(specs: list[ToolSpec]) -> list[str]
def get_spec(specs: list[ToolSpec], name: str) -> ToolSpec | None
```

### 1.4. Экспорт

В `blocksnet_agent/tools/__init__.py` — добавить в `__all__`
`build_catalog`, `ToolSpec`, `TOOL_BLOCKLIST` (импорт внутри функции или
в конце файла, чтобы не создать циклический импорт с `catalog.py`).

---

## Тесты — `tests/test_tool_catalog.py`

```python
def test_catalog_covers_all_non_blocked_tools(tmp_path):
    """Каталог = make_tools() минус blocklist. Число не хардкодим (инвариант 7)."""
    state = {}
    tools = make_tools(state, tmp_path, tmp_path)
    specs = build_catalog({}, tmp_path, tmp_path)
    expected = {t.name for t in tools} - TOOL_BLOCKLIST
    assert {s.name for s in specs} == expected


def test_submit_answer_is_blocked(tmp_path):
    assert "submit_answer" not in {s.name for s in build_catalog({}, tmp_path, tmp_path)}


def test_rag_tools_present(tmp_path):
    """find_tools/get_tool_help детерминированы и обязаны быть в каталоге."""
    names = {s.name for s in build_catalog({}, tmp_path, tmp_path)}
    assert {"find_tools", "get_tool_help"} <= names


def test_every_spec_has_short_description_and_input_schema(tmp_path):
    for spec in build_catalog({}, tmp_path, tmp_path):
        assert spec.short and "\n" not in spec.short
        assert spec.args_schema.get("type") == "object"


def test_catalog_does_not_mutate_tool_behaviour(tmp_path):
    """Построение каталога не должно ломать вызов инструмента."""
    specs = build_catalog({}, tmp_path, tmp_path)
    spec = get_spec(specs, "list_cached_data")
    assert isinstance(spec.tool.invoke({}), str)
```

Замечание для исполнителя: `make_tools` может требовать существующих
`data_dir`/`output_dir` — использовать `tmp_path`; сама фабрика данные не
читает, чтение происходит внутри вызова инструмента.

---

## DoD

- [ ] `blocksnet_agent/tools/catalog.py` существует, `registry.py` не изменён
      (`git diff --stat blocksnet_agent/tools/registry.py` — пусто)
- [ ] `blocksnet_agent/agent.py` не изменён
- [ ] `python -m pytest tests/test_tool_catalog.py -q` — зелёный
- [ ] `python -m pytest -q` — не хуже `baseline.txt`
- [ ] Проверено вручную: `len(build_catalog({}, ..., ...)) == 32`
      (значение сверить с `tools_snapshot.txt`, **в тест не хардкодить**)
- [ ] Коммит `a2a/01: tool catalog as single source of truth`

## Не делать

- Не переименовывать и не переписывать `registry.py`.
- Не менять порядок операций в `make_tools()` (мемоизация обязана быть
  последней — иначе streak-лимит RAG и кэш перестанут работать).
- Не выносить инструменты из фабрик в модульные функции: они замкнуты
  над `state`, вне фабрики их не существует.
- Не хардкодить 32/33 в тестах.

## Откат

`git rm blocksnet_agent/tools/catalog.py tests/test_tool_catalog.py` +
откат правки `tools/__init__.py`. Остальной код не затронут.
