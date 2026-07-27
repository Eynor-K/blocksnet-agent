"""Local MCP wrapper for BlocksNetAgent.

a2a/03: ленивый re-export через ``__getattr__`` — ``import blocksnet_mcp`` больше
не тянет ``agent_tool`` (а через него и потенциальные LLM-зависимости). Legacy
путь ``from blocksnet_mcp import analyze_urban_question`` продолжает работать.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["analyze_urban_question"]


def __getattr__(name: str) -> Any:
    """Ленивый импорт legacy-инструмента.

    Импортируется только при реальном обращении (``blocksnet_mcp.analyze_urban_question``
    или через shim ``tools_mcp``). Это критично для шага 03 — без LLM-конфига
    ``import blocksnet_mcp`` должен работать и не тянуть langchain.
    """
    if name == "analyze_urban_question":
        from blocksnet_mcp.agent_tool import analyze_urban_question

        return analyze_urban_question
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover — only for type checkers
    from blocksnet_mcp.agent_tool import analyze_urban_question