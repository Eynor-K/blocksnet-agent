"""Backward-compat shim для legacy-импорта ``blocksnet_mcp.tools_mcp``.

a2a/03: модуль переехал в ``blocksnet_mcp.agent_tool``. Этот файл сохранён
ради обратной совместимости — клиенты и тесты, импортирующие
``from blocksnet_mcp.tools_mcp import analyze_urban_question``, продолжают
работать.

DEPRECATED: новый код должен импортировать ``blocksnet_mcp.agent_tool``.
"""

from __future__ import annotations

from blocksnet_mcp.agent_tool import *  # noqa: F401,F403
from blocksnet_mcp.agent_tool import analyze_urban_question  # noqa: F401

__all__ = ["analyze_urban_question"]