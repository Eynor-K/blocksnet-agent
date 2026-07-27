"""``python -m blocksnet_mcp`` — точка входа в MCP-сервер.

a2a/03: до этого шага файл отсутствовал — нужно было запускать как
``python -m blocksnet_mcp.server``. Теперь стандартный путь — ``python -m blocksnet_mcp``.
"""

from __future__ import annotations

from blocksnet_mcp.server import main

if __name__ == "__main__":
    main()