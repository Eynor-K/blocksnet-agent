"""A2A-сервис для BlocksNetAgent.

Шаг 05 a2a-рефакторинга. Доступ через ``python -m blocksnet_agent.a2a``
или ``python -m blocksnet_agent`` (через ``__main__.py``).

Главные модули:
- ``settings`` — A2ASettings (наследует agent.Settings).
- ``schemas`` — Pydantic-модели входов/выходов skill-ов.
- ``task_manager`` — жизненный цикл задач (submitted/working/completed/...).
- ``executor`` — мост A2A ↔ BlocksNetAgent.
- ``agent_card`` — карточка агента (skills, capabilities).
- ``skills`` — реализации run_pipeline / analyze_urban_question.
- ``server`` — сборка FastAPI + uvicorn.
"""

from __future__ import annotations

__all__ = [
    "A2ASettings",
    "TaskManager",
    "TaskState",
    "TaskRecord",
    "execute_run_pipeline",
]


def __getattr__(name: str):  # pragma: no cover — для удобства импорта
    """Ленивый импорт подмодулей — ускоряет ``import blocksnet_agent.a2a``."""
    if name == "A2ASettings":
        from blocksnet_agent.a2a.settings import A2ASettings
        return A2ASettings
    if name in ("TaskManager", "TaskState", "TaskRecord"):
        from blocksnet_agent.a2a import task_manager
        return getattr(task_manager, name)
    if name == "execute_run_pipeline":
        from blocksnet_agent.a2a.executor import execute_run_pipeline
        return execute_run_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")