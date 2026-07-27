"""Единая точка правды о наборе инструментов для MCP-сервера.

Каталог строится поверх ``make_tools()`` — той же фабрики, которой пользуется агент.
Агент продолжает работать через ``make_tools()`` напрямую (каталог ему не нужен);
MCP-сервер на шаге 03 будет брать инструменты только отсюда, чтобы исключить
расхождение между двумя потребителями (инвариант 3 в implementation/README.md).

Важно:
- Каталог привязан к ``state``, не кэшируется глобально — каждый запуск агента
  создаёт свой набор, чтобы мемоизация и RAG-streak жили в своём контексте.
- ``submit_answer`` — терминальный инструмент агентского цикла, пишет
  ``state["_submitted_answer"]`` и завершает PTR. В MCP его экспонировать
  нельзя (инвариант 5): он зарезан в ``TOOL_BLOCKLIST`` и по умолчанию скрыт.
"""

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
    """Описание одного инструмента для внешней экспозиции (MCP/A2A)."""

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
    """Строит каталог инструментов поверх ``make_tools()``.

    Единственная точка, из которой MCP-сервер узнаёт, что экспонировать.
    Агент продолжает пользоваться ``make_tools()`` напрямую — каталог ему не нужен.

    Args:
        state: состояние запуска (передаётся в ``make_tools`` для мемоизации).
        data_dir: путь к данным города (передаётся в инструменты).
        output_dir: путь к run-каталогу для артефактов.
        include_blocked: если True — включить заблокированные (``submit_answer``).
            Используется только в тестах; MCP-сервер всегда вызывает с ``False``.

    Returns:
        Список ``ToolSpec`` в порядке, который вернул ``make_tools()``.
    """
    registry: dict[str, dict[str, str]] = {}
    tools = make_tools(state, data_dir, output_dir, registry_out=registry)

    specs: list[ToolSpec] = []
    for tool in tools:
        if not include_blocked and tool.name in TOOL_BLOCKLIST:
            continue
        meta = registry.get(tool.name) or {}
        # ``short`` — первая строка docstring (после build_tool_registry). Фолбэк
        # на ``tool.description`` нужен на случай, если в реестре имени нет
        # (теоретически не должно случаться, но не валим каталог из-за этого).
        short = meta.get("short") or (tool.description or "").strip().splitlines()[0:1]
        if isinstance(short, list):
            short = short[0] if short else tool.name
        short = short or tool.name
        # ``full`` — полная справка из реестра (с аугментацией для service-tools).
        full = meta.get("full") or tool.description or short
        # ``args_schema`` — JSON Schema из Pydantic-модели. Фолбэк на пустую
        # объект-схему, если у инструмента нет args (например, ``load_blocks``).
        args_schema: dict[str, Any]
        if tool.args_schema is not None:
            try:
                args_schema = tool.args_schema.model_json_schema()
            except Exception:
                args_schema = {"type": "object", "properties": {}}
        else:
            args_schema = {"type": "object", "properties": {}}
        # Гарантируем object-shape — это требование MCP inputSchema.
        if args_schema.get("type") != "object":
            args_schema = {"type": "object", "properties": {}}
        specs.append(
            ToolSpec(
                name=tool.name,
                short=short,
                full=full,
                args_schema=args_schema,
                tool=tool,
            )
        )
    return specs


def catalog_names(specs: list[ToolSpec]) -> list[str]:
    """Имена инструментов в каталоге — для логирования и smoke-проверок."""
    return [s.name for s in specs]


def get_spec(specs: list[ToolSpec], name: str) -> ToolSpec | None:
    """Найти спецификацию по имени; ``None``, если нет (или имя заблокировано)."""
    for s in specs:
        if s.name == name:
            return s
    return None


# Импорт внизу файла: ``make_tools`` живёт в ``blocksnet_agent.tools``, который
# уже импортирует ``catalog`` через свой ``__init__``. Чтобы не создать цикл,
# импортируем лениво внутри функций (build_catalog уже это делает).
from blocksnet_agent.tools import make_tools  # noqa: E402

__all__ = [
    "build_catalog",
    "catalog_names",
    "get_spec",
    "ToolSpec",
    "TOOL_BLOCKLIST",
]