"""``python -m blocksnet_agent`` — shortcut на A2A-сервис.

a2a/05: задача 4.3 (отложенная с шага 04). Импортирует ``main`` из ``a2a.server``
и запускает uvicorn.

Использование::

    python -m blocksnet_agent

Опциональные env-переменные:
- ``A2A_HOST`` — default ``0.0.0.0``
- ``A2A_PORT`` — default ``8080``
- ``A2A_PUBLIC_URL`` — если сервис за reverse-proxy
- ``CHAT_URL``/``API_KEY``/``MODEL`` — LLM-конфиг (для run_pipeline)
- ``DATA_DIR``/``OUTPUT_DIR`` — пути к данным
- ``DEADLINE_SEC`` — дедлайн на задачу
"""

from __future__ import annotations

from blocksnet_agent.a2a.server import main

if __name__ == "__main__":
    main()