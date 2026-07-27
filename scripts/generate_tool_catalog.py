"""Генератор ``docs/mcp_tool_catalog.md`` из живого каталога.

Шаг 08 a2a-рефакторинга. Скрипт обходит ``build_catalog()`` и формирует
Markdown-каталог со всеми 32 инструментами: имя, короткое описание,
JSON Schema входа, полная справка, пометка «требует сессии» для
инструментов, читающих ``state[result_key]``.

Запускать::

    python scripts/generate_tool_catalog.py

Файл ``docs/mcp_tool_catalog.md`` помечен как auto-generated — ручные
правки теряются при следующем запуске. Тест
``tests/test_tool_catalog_docs.py`` сверяет закоммиченный файл с
актуальной генерацией (защита от протухания).

Источник истины по контракту — ``blocksnet_agent/tools/catalog.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from blocksnet_agent.tools.catalog import (  # noqa: E402
    TOOL_BLOCKLIST,
    ToolSpec,
    build_catalog,
    get_spec,
)


# Инструменты, которые читают state["<result_key>"] — помечаем «требует сессии».
# Список взят из docstring'ов tools/* — список не исчерпывающий, поэтому
# дополнительно используем эвристику: имя начинается с ``get_``.
_SESSION_REQUIRED_PATTERNS = (
    "get_analysis_results",
    "get_metric_for_block",
    "render_metric_map",
    "list_cached_data",
)


def _requires_session(spec_name: str) -> bool:
    if spec_name.startswith("get_") and spec_name != "get_tool_help":
        return True
    return spec_name in _SESSION_REQUIRED_PATTERNS


def _format_schema(args_schema: dict[str, Any]) -> str:
    """JSON Schema → Markdown-блок (компактно)."""
    properties = args_schema.get("properties") or {}
    required = set(args_schema.get("required") or [])
    if not properties:
        return "*(без аргументов)*"
    lines = []
    for name, schema in sorted(properties.items()):
        type_str = schema.get("type", "any")
        desc = schema.get("description", "").strip()
        marker = "**обязательный**" if name in required else "необязательный"
        line = f"- `{name}` (`{type_str}`, {marker})"
        if desc:
            line += f" — {desc}"
        if "default" in schema and name not in required:
            default = schema["default"]
            if default is not None:
                line += f" _(default: `{json.dumps(default)})`_"
        lines.append(line)
    return "\n".join(lines)


def generate_catalog_markdown() -> str:
    """Собирает Markdown-каталог из build_catalog()."""
    from pathlib import Path as _P

    settings_module = sys.modules.get("blocksnet_mcp.settings")
    if settings_module is None:
        from blocksnet_mcp.settings import get_mcp_settings

        settings = get_mcp_settings()
    else:
        settings = settings_module.get_mcp_settings()
    data_dir = settings.data_dir
    output_dir = settings.output_dir

    specs = build_catalog({}, data_dir, output_dir)

    header = """# MCP Tool Catalog

> **Не редактировать руками.** Этот файл генерируется из живого кода
> скриптом ``scripts/generate_tool_catalog.py`` через
> ``build_catalog()`` (``blocksnet_agent/tools/catalog.py``).
> Тест ``tests/test_tool_catalog_docs.py`` гарантирует, что закоммиченная
> версия совпадает с актуальной.

MCP-сервер ``blocksnet_mcp`` экспонирует {total} инструментов ({exposed} каталожных
+ 3 служебных: ``open_session``, ``close_session``, ``session_info``).

Из каталожных инструментов:

- {session_required} читают ``state[result_key]`` — вызывайте их **после** ``load_blocks``,
  ``compute_*``, и в рамках сессии (``session_id`` в каждом вызове).
- Остальные — идемпотентные (``list_*``, ``compute_*`` с дефолтами, ``load_*``) либо
  генераторы (``suggest_target_blocks``, ``render_metric_map``).

Все инструменты принимают первым аргументом ``session_id: str = "default"``.
``submit_answer`` (``TOOL_BLOCKLIST``) НЕ экспонируется — это терминальный
инструмент агентского цикла, см. ``blocksnet_agent/tools/catalog.py``.

---

""".format(
        total=len(specs) + 3,
        exposed=len(specs),
        session_required=sum(1 for s in specs if _requires_session(s.name)),
    )

    sections: list[str] = [header]

    for spec in sorted(specs, key=lambda s: s.name):
        section_required = (
            " ⚠️ **требует сессии** (читает `state[result_key]`)"
            if _requires_session(spec.name)
            else ""
        )
        section = (
            f"## `{spec.name}`{section_required}\n\n"
            f"**Краткое описание:** {spec.short}\n\n"
            f"**Справка:**\n\n```\n{spec.full}\n```\n\n"
            f"**Вход:**\n\n{_format_schema(spec.args_schema)}\n\n"
            f"**ToolSpec:** `name={spec.name}`, `short={spec.short!r}`\n\n"
            "---\n\n"
        )
        sections.append(section)

    footer = (
        "## Служебные инструменты\n\n"
        "Эти три инструмента экспонируются только на уровне MCP (не входят в\n"
        "каталог агента):\n\n"
        "- `open_session(session_id='default', scenario_id=None, project_id=None)` —\n"
        "  создаёт/возвращает сессию. `scenario_id` валидируется\n"
        "  whitelist'ом `[a-zA-Z0-9_-]{1,64}` (path-traversal защита).\n"
        "- `close_session(session_id)` — закрывает сессию, освобождает state.\n"
        "- `session_info(session_id='default')` — диагностика (без значений state).\n\n"
        "Сценарий-контракт см. `docs/tool_contract.md` § «Сессии MCP».\n"
    )
    sections.append(footer)

    return "".join(sections)


def write_catalog(path: Path) -> None:
    """Генерирует и пишет Markdown в ``path``."""
    content = generate_catalog_markdown()
    path.write_text(content, encoding="utf-8")
    print(f"Wrote {path} ({len(content)} bytes, {len(content.splitlines())} lines)")


if __name__ == "__main__":
    target = PROJECT_ROOT / "docs" / "mcp_tool_catalog.md"
    write_catalog(target)