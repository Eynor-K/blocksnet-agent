"""Pydantic-схемы для A2A-skill входов и выходов.

Шаг 05 a2a-рефакторинга. Схемы описывают контракт skill-ов (не HTTP/JSON-RPC —
это в SDK).

Контракт ответа ``SkillOutput`` идентичен MCP-варианту ``analyze_urban_question``
(``blocksnet_mcp.serialize.to_json()`` + поля ``status``/``tool``/``run_id``/
``run_dir``/``error_code``). Это гарантирует, что downstream-агенты в MAS могут
ходить и в MCP, и в A2A — формат один.

Зафиксировано в ``docs/tool_contract.md`` (v1/v2 будут в шаге 08).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunPipelineInput(BaseModel):
    """Вход skill-а ``run_pipeline``: вопрос + опциональные параметры."""

    question: str = Field(..., description="Городской вопрос для анализа")
    max_iterations: int | None = Field(
        default=None,
        description="Переопределить лимит итераций агента (None → из settings)",
    )
    # Шаг 06 (auth + context): scenario_id/project_id из авторизованного запроса.
    # Пока — None-поля для обратной совместимости.
    scenario_id: str | None = Field(default=None, description="шаг 06")
    project_id: str | None = Field(default=None, description="шаг 06")


class AnalyzeUrbanQuestionInput(BaseModel):
    """Вход ``analyze_urban_question`` (back-compat skill)."""

    question: str
    max_iterations: int | None = None
    scenario_id: str | None = Field(default=None, description="шаг 06")
    project_id: str | None = Field(default=None, description="шаг 06")


class SkillOutput(BaseModel):
    """Результат skill-а: тот же dict, что отдаёт ``analyze_urban_question``
    в MCP-варианте. Поля НЕ переименовываем — это публичный контракт.
    """

    # Модель используется как структурный тип для type hints; реальный payload
    # это dict, который A2A SDK сериализует в JSON. Поэтому держим модель
    # permissive — она нужна для документации и валидации только в тестах.
    model_config = {"extra": "allow"}

    status: str = Field(default="ok", description="ok | partial | failed")
    tool: str = Field(default="run_pipeline", description="Имя skill-а")
    question: str | None = None
    analysis_plan: str | None = None
    result: str | None = None
    output: str | None = None  # legacy alias for ``result``
    hypotheses: list[Any] | None = None
    measured: list[Any] | None = None
    recommendation_blocks: list[int] | None = None
    confidence: float | None = None
    limitations: list[str] | None = None
    artifacts: list[Any] | None = None
    run_id: str | None = None
    run_dir: str | None = None
    error: str | None = None
    error_code: str | None = None

    # Overlay (P1.6): структурные рекомендации из гипотезных слоёв.
    overlay_candidates: list[dict[str, Any]] | None = None
    overlay_meta: dict[str, Any] | None = None


__all__ = [
    "RunPipelineInput",
    "AnalyzeUrbanQuestionInput",
    "SkillOutput",
]