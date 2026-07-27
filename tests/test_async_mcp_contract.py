"""P0.2: in-memory MCP contract-тест — analyze_urban_question не падает транспортным ExceptionGroup.

Тесты не делают реальных LLM-вызовов: agent.run() заглушается через monkeypatch.
"""
from __future__ import annotations

from typing import Any

import pytest


def test_analyze_urban_question_validation_returns_structured_response() -> None:
    """P0.2: ошибка валидации → структурированный dict, не raise."""
    from blocksnet_mcp.tools_mcp import analyze_urban_question

    result = analyze_urban_question("")
    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert result["error_code"] == "VALIDATION_ERROR"
    assert "question" in result["error"]


def test_analyze_urban_question_requires_positive_iterations() -> None:
    """P0.2: max_iterations=0 → структурированный failed, не raise."""
    from blocksnet_mcp.tools_mcp import analyze_urban_question

    result = analyze_urban_question("test", max_iterations=0)
    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert result["error_code"] == "VALIDATION_ERROR"


def test_progress_callback_accepted_without_llm(monkeypatch) -> None:
    """P0.2: progress callback регистрируется в start_run без реального LLM-вызова.

    Заглушаем BlocksNetAgent.run чтобы вернуть фиктивный результат — проверяем,
    что start_run принимает callback и не падает.
    """
    from blocksnet_mcp import tools_mcp
    from blocksnet_agent import BlocksNetAgent

    seen: list[tuple[int, int, str]] = []

    def cb(done: int, total: int, message: str) -> None:
        seen.append((done, total, message))

    # Заглушка: agent.run возвращает фиктивный AgentResult-like dict.
    class _FakeResult:
        output = "Fake result"
        run_id = "test-fake"
        run_dir = ""

    def _fake_run(self, task):
        return _FakeResult()

    monkeypatch.setattr(BlocksNetAgent, "run", _fake_run)

    result = tools_mcp.analyze_urban_question(
        "что разместить в квартале 3442?",
        max_iterations=1,
        progress_callback=cb,
    )
    assert isinstance(result, dict)
    assert "status" in result
    # callback мог не сработать (заглушка не вызывает инструменты), но регистрация прошла.
    # Если сработал — проверяем формат.
    for done, total, message in seen:
        assert isinstance(done, int)
        assert isinstance(message, str)


def test_agent_exception_returns_structured_failed(monkeypatch) -> None:
    """P0.2: исключение внутри агента → status=failed с error_code, не голая строка в isError."""
    from blocksnet_mcp import tools_mcp
    from blocksnet_agent import BlocksNetAgent

    def _boom_run(self, task):
        raise RuntimeError("LLM connection refused")

    monkeypatch.setattr(BlocksNetAgent, "run", _boom_run)

    result = tools_mcp.analyze_urban_question("test question", max_iterations=1)
    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert result["error_code"] == "AGENT_EXCEPTION"
    assert "LLM connection refused" in result["error"]