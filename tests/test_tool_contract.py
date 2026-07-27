from __future__ import annotations

import pytest

from blocksnet_mcp.tools_mcp import analyze_urban_question


def test_analyze_urban_question_requires_question() -> None:
    # P0.2: ошибка — легитимный результат анализа (структурированный failed-ответ).
    result = analyze_urban_question("")
    assert result["status"] == "failed"
    assert result["error_code"] == "VALIDATION_ERROR"
    assert "question" in result["error"]


def test_analyze_urban_question_requires_positive_iterations() -> None:
    result = analyze_urban_question("test", max_iterations=0)
    assert result["status"] == "failed"
    assert result["error_code"] == "VALIDATION_ERROR"
    assert "max_iterations" in result["error"]
