"""Конверт ответа MCP-сервера (Q5 из open_questions.md).

Шаг 03 a2a-рефакторинга. Каждый tool-call возвращает структуру::

    {
        "status": "ok" | "partial" | "failed",
        "tool": "<name>",
        "session_id": "<sid>",
        "text": "<raw tool output as-is>",
        "artifacts": ["<path1>", ...],
        "error_code": "TOOL_FAILED" | "TOOL_EXCEPTION" | "VALIDATION_ERROR" | ...,
        "error": "<message>",  # только при status != "ok"
    }

Главные инварианты:
- Текст инструмента передаётся как есть (инвариант 4 плана).
- ``status`` определяется по тексту через маркеры, известные агенту (см. ниже).
- ``error_code`` конверта совпадает с уже используемыми в ``tools_mcp.py``
  (``VALIDATION_ERROR``, ``AGENT_EXCEPTION``) — не плодим синонимы.
- Исключения внутри инструмента → ``status="failed"`` + ``TOOL_EXCEPTION``,
  а не транспортная ошибка (это уже принцип P0.2 в текущем сервере).

a2a/07 (Docker): классификация маркеров дублируется локально, чтобы
``import blocksnet_mcp.envelope`` НЕ тянул ``blocksnet_agent`` (а через
него ``langgraph``/``tiktoken``). Это позволяет MCP-образу собираться
без LLM-зависимостей — проверяется ``tests/test_image_deps.py``.
"""

from __future__ import annotations

from typing import Any

# Маркеры, по которым текст инструмента классифицируется как failed.
# Должны совпадать с ``blocksnet_agent.metrics.FAILURE_MARKERS`` и
# ``blocksnet_agent.tools._STALE_OBSERVATION_MARKERS``. Дублируем
# намеренно (см. docstring) — это короткая константа, дрейфаться не должна.
_FAILURE_MARKERS = (
    "Ошибка:",
    "Traceback",
    "Exception",
    "not found",
    "не найден",
    "NO_DATA",
    "REPEATED_FAILED_CALL",
)
_STALE_OBSERVATION_MARKERS = (
    "нет кэшированных",
    "Сначала вызови",
    "сначала вызови",
    "не найден",
    "не удалось",
)


def is_failed_observation(text: str) -> bool:
    """Локальная копия логики ``blocksnet_agent.tools.is_failed_observation``.

    Дубликат ради разделения зависимостей MCP-образа. Источник истины —
    ``blocksnet_agent.tools.is_failed_observation`` (тест на дрейф — см.
    ``tests/test_image_deps.py::test_envelope_classification_matches_agent``).
    """
    body = (text or "").strip()
    if not body:
        return False
    if body.startswith(_FAILURE_MARKERS):
        return True
    return any(marker in body for marker in _STALE_OBSERVATION_MARKERS)


# Канонические коды ошибок конверта. Согласованы с текущим tools_mcp.py:
# VALIDATION_ERROR, AGENT_EXCEPTION, LLM_NOT_CONFIGURED — остались как есть.
ERROR_CODE_TOOL_FAILED = "TOOL_FAILED"           # инструмент вернул текст-ошибку
ERROR_CODE_TOOL_EXCEPTION = "TOOL_EXCEPTION"     # исключение в инструменте
ERROR_CODE_VALIDATION_ERROR = "VALIDATION_ERROR"  # неверные аргументы
ERROR_CODE_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"  # сессия не найдена
ERROR_CODE_DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"  # дедлайн истёк
ERROR_CODE_LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"  # LLM не настроен (analyze_urban_question)


def build_envelope(
    tool: str,
    session_id: str,
    text: str,
    artifacts: list[str] | None = None,
    *,
    error_code: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Строит конверт ответа MCP-инструмента.

    Args:
        tool: имя инструмента (для логирования/диагностики).
        session_id: id сессии, в которой вызван инструмент.
        text: текст-результат инструмента (как есть, без переформатирования).
        artifacts: пути к файлам, которые инструмент создал в этом вызове.
        error_code: явный код ошибки (для случаев, когда инструмент бросил
            исключение или сессия не найдена). Если None — статус выводится
            из текста через ``is_failed_observation``.
        error: человекочитаемое сообщение об ошибке (None при ok).

    Returns:
        Словарь с фиксированным набором ключей.
    """
    payload: dict[str, Any] = {
        "tool": tool,
        "session_id": session_id,
        "text": text,
        "artifacts": list(artifacts or []),
    }
    if error_code is not None:
        payload["error_code"] = error_code
        payload["error"] = error or ""
        payload["status"] = "failed"
    elif is_failed_observation(text or ""):
        payload["status"] = "failed"
        payload["error_code"] = ERROR_CODE_TOOL_FAILED
        # Не выдумываем своё сообщение — текст уже содержит причину.
        payload["error"] = text or ""
    else:
        payload["status"] = "ok"
    return payload


__all__ = [
    "build_envelope",
    "ERROR_CODE_TOOL_FAILED",
    "ERROR_CODE_TOOL_EXCEPTION",
    "ERROR_CODE_VALIDATION_ERROR",
    "ERROR_CODE_SESSION_NOT_FOUND",
    "ERROR_CODE_DEADLINE_EXCEEDED",
    "ERROR_CODE_LLM_NOT_CONFIGURED",
]