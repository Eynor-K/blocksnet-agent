"""``python -m blocksnet_agent.a2a`` — entrypoint в A2A-сервис.

a2a/05: uvicorn с FastAPI-приложением из ``server.py``.
"""

from __future__ import annotations

from blocksnet_agent.a2a.server import main

if __name__ == "__main__":
    main()