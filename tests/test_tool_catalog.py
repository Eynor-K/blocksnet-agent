"""Тесты для ``blocksnet_agent.tools.catalog``.

Шаг 01 a2a-рефакторинга: каталог инструментов — общая точка правды для
MCP-сервера (агент продолжает работать через ``make_tools()`` напрямую).

Инварианты, которые тесты защищают:
- 7 (см. implementation/README.md): число инструментов НЕ хардкодится —
  сверяемся с ``make_tools()``, не с константой 32/33.
- 3: ``registry.py`` остаётся нетронутым, экспорт в каталоге не зависит от
  внутреннего устройства RAG-инструментов.
- 4: текстовое описание не модифицируется — только берётся из реестра.
- 5: ``submit_answer`` заблокирован в каталоге (MCP его не видит).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from blocksnet_agent.tools import make_tools
from blocksnet_agent.tools.catalog import (
    TOOL_BLOCKLIST,
    ToolSpec,
    build_catalog,
    catalog_names,
    get_spec,
)


# --- фикстуры ---------------------------------------------------------------


@pytest.fixture
def specs(tmp_path: Path) -> list[ToolSpec]:
    """Каталог инструментов во временном каталоге (data_dir/output_dir не читаются)."""
    return build_catalog({}, tmp_path, tmp_path)


@pytest.fixture
def all_tools(tmp_path: Path) -> list:
    """Полный набор инструментов ``make_tools()`` — для сверки состава."""
    return make_tools({}, tmp_path, tmp_path)


# --- тесты ------------------------------------------------------------------


def test_catalog_covers_all_non_blocked_tools(
    specs: list[ToolSpec], all_tools: list
) -> None:
    """Каталог = make_tools() минус blocklist. Число не хардкодим (инвариант 7)."""
    expected = {t.name for t in all_tools} - TOOL_BLOCKLIST
    assert {s.name for s in specs} == expected


def test_catalog_size_matches_snapshot(specs: list[ToolSpec], all_tools: list) -> None:
    """Размер каталога = размер make_tools() - 1 (submit_answer). Не литерал."""
    assert len(specs) == len(all_tools) - 1


def test_submit_answer_is_blocked(specs: list[ToolSpec]) -> None:
    """submit_answer — терминальный инструмент агента, в MCP не уходит (инвариант 5)."""
    assert "submit_answer" not in {s.name for s in specs}
    assert "submit_answer" not in catalog_names(specs)


def test_rag_tools_present(specs: list[ToolSpec]) -> None:
    """find_tools/get_tool_help детерминированы и обязаны быть в каталоге."""
    names = {s.name for s in specs}
    assert {"find_tools", "get_tool_help"} <= names


def test_every_spec_has_short_description_and_input_schema(specs: list[ToolSpec]) -> None:
    """У каждого spec есть непустое short (одна строка) и валидная JSON Schema входа."""
    for spec in specs:
        assert spec.short, f"{spec.name}: short is empty"
        assert "\n" not in spec.short, f"{spec.name}: short must be one line, got {spec.short!r}"
        assert spec.args_schema.get("type") == "object", (
            f"{spec.name}: args_schema.type is {spec.args_schema.get('type')!r}, expected 'object'"
        )


def test_every_spec_has_full_description(specs: list[ToolSpec]) -> None:
    """Full-описание есть (для MCP-выдачи через tools/list)."""
    for spec in specs:
        assert spec.full, f"{spec.name}: full description is empty"
        assert len(spec.full) >= len(spec.short), (
            f"{spec.name}: full shorter than short — реестр не подхватился"
        )


def test_catalog_does_not_mutate_tool_behaviour(specs: list[ToolSpec]) -> None:
    """Построение каталога не должно ломать вызов инструмента (инвариант 4)."""
    spec = get_spec(specs, "list_cached_data")
    assert spec is not None
    # ``list_cached_data`` не имеет обязательных аргументов и возвращает str.
    # Если ``build_catalog`` испортил объект tool, вызов упадёт.
    result = spec.tool.invoke({})
    assert isinstance(result, str)


def test_get_spec_returns_none_for_unknown(specs: list[ToolSpec]) -> None:
    """``get_spec`` возвращает None для неизвестного имени (не KeyError)."""
    assert get_spec(specs, "nonexistent_tool_xyz") is None


def test_get_spec_returns_spec_for_known(specs: list[ToolSpec]) -> None:
    """``get_spec`` возвращает spec для известного имени."""
    spec = get_spec(specs, "find_tools")
    assert spec is not None
    assert spec.name == "find_tools"


def test_include_blocked_exposes_submit_answer(tmp_path: Path) -> None:
    """``include_blocked=True`` возвращает submit_answer — для тестов/agent-side use."""
    specs = build_catalog({}, tmp_path, tmp_path, include_blocked=True)
    assert "submit_answer" in {s.name for s in specs}


def test_catalog_order_matches_make_tools(
    specs: list[ToolSpec], all_tools: list
) -> None:
    """Порядок инструментов в каталоге совпадает с ``make_tools()`` (без блоклиста).

    Это не инвариант функциональной корректности, но помогает при диагностике
    рассинхрона между двумя источниками: если порядок разный — что-то
    пересортировали, искать причину.
    """
    expected_order = [t.name for t in all_tools if t.name not in TOOL_BLOCKLIST]
    assert catalog_names(specs) == expected_order


def test_blocklist_is_immutable(specs: list[ToolSpec]) -> None:
    """TOOL_BLOCKLIST — frozenset, нельзя случайно мутировать снаружи."""
    with pytest.raises(AttributeError):
        TOOL_BLOCKLIST.add("submit_answer")  # type: ignore[attr-defined]
    # И в самом каталоге submit_answer нет — независимо от попыток обхода.
    assert "submit_answer" not in {s.name for s in specs}