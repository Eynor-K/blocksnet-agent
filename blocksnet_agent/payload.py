"""Общая обёртка payload-а для результатов ``BlocksNetAgent``.

Шаг 05 a2a-рефакторинга: ``_build_payload`` жил в ``blocksnet_mcp/agent_tool.py``
и зависел от ``blocksnet_mcp.serialize.to_json``. Это создавало неправильное
направление зависимости при попытке переиспользовать из A2A-сервиса
(``blocksnet_agent → blocksnet_mcp``).

Решение — вынести общий формат ответа сюда. ``agent_tool.py`` (MCP) и
executor A2A-сервиса используют одну и ту же функцию, чтобы контракт
ответа (``status``/``tool``/``run_id``/``run_dir``/``error_code``) не разъехался.

Формат зафиксирован в ``docs/tool_contract.md`` и покрыт тестами в
``tests/test_serialize.py`` и ``tests/test_tool_contract.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_payload(
    result: Any,
    run_dir: str,
    *,
    tool: str,
    status: str = "ok",
    error: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """P0.2: единая обёртка ответа — структурированный JSON со статусом.

    Args:
        result: AgentResult (или его mock с полями ``output``/``run_id``/``run_dir``).
        run_dir: путь к run-каталогу.
        tool: имя инструмента (для унификации envelope с MCP).
        status: ``ok``/``partial``/``failed``.
        error: человекочитаемое сообщение (None при ok).
        error_code: код ошибки (None при ok).

    Returns:
        Dict, который идёт клиенту. Поля::

            {
              "output": "...",          # если error
              ...поля to_json(result)... # если !error
              "status": "ok"|"partial"|"failed",
              "tool": "<name>",
              "run_id": "<id>",
              "run_dir": "<path>",
              "error": "<msg>",         # если status == failed
              "error_code": "<code>",   # если status == failed
            }
    """
    # Импортируем лениво — ``to_json`` нужен только при успешном пути.
    # Это лечит «import blocksnet_agent тянет serialize» в сценариях,
    # где payload собирается для ошибки (типичный случай при тестах/валидации).
    if not error:
        from blocksnet_mcp.serialize import to_json

        payload = to_json(result)
    else:
        payload = {"output": str(getattr(result, "output", ""))}

    payload["status"] = status
    payload["tool"] = tool

    # run_id: из result, иначе из run_dir (имя каталога).
    run_id_value: str | None = None
    if not error:
        rid = getattr(result, "run_id", None)
        if rid:
            run_id_value = str(rid)
    if not run_id_value and run_dir:
        run_id_value = Path(run_dir).name
    if run_id_value is not None:
        payload["run_id"] = run_id_value
    if run_dir:
        payload["run_dir"] = run_dir
    if error:
        payload["error"] = error
    if error_code:
        payload["error_code"] = error_code
    return payload


# Обратная совместимость со старыми внутренними вызывающими — алиас для
# тех мест, где код использовал ``_build_payload`` напрямую (тесты, shim).
_build_payload = build_payload


__all__ = ["build_payload"]