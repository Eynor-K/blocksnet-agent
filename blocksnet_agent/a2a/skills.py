"""Реестр A2A-skills: ``run_pipeline`` и ``analyze_urban_question``.

Шаг 05 a2a-рефакторинга. Контракт:
- ``run_pipeline`` — основной skill. Создаёт задачу, стримит статусы,
  отдаёт артефакты.
- ``analyze_urban_question`` — back-compat обёртка: вызывает ``run_pipeline``
  и **блокирующе** ждёт терминального статуса, отдаёт финальный JSON.
  Никакой второй реализации pipeline (см. Q2 в open_questions.md).

Реестр возвращает ``list[SkillSpec]`` — плоский список для ``agent_card.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from blocksnet_agent.a2a.schemas import (
    AnalyzeUrbanQuestionInput,
    RunPipelineInput,
)


@dataclass(frozen=True)
class SkillSpec:
    """Описание одного skill для Agent Card + реестра."""

    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    examples: tuple[str, ...]
    input_model: type
    # Реализация: ``run(input_dict, task_manager, output_dir, data_dir,
    # deadline_sec, progress_cb) -> dict``. Описывает логику skill-а.
    runner: Any  # callable — тип намеренно Any, чтобы не возиться с Callable[...]


def _run_run_pipeline(
    input_payload: dict[str, Any],
    task_manager: Any,
    output_dir: Any,
    data_dir: Any,
    deadline_sec: int | None,
    progress_cb: Any,
) -> dict[str, Any]:
    """Реализация skill-а ``run_pipeline``.

    Создаёт задачу через TaskManager, блокирующе ждёт терминального статуса.
    Возвращает финальный payload (с ``status="ok"|"partial"|"failed"``).
    """
    from blocksnet_agent.a2a.executor import execute_run_pipeline

    inp = RunPipelineInput.model_validate(input_payload)

    # Хелпер: runner для TaskManager — вызывается в рабочем потоке.
    def _task_runner(record: Any, internal_progress_cb: Any) -> dict[str, Any]:
        # ``internal_progress_cb`` дросселирует (TaskManager), а ``progress_cb``
        # наружу — без дросселя. Объединяем: внешний тоже получит события.
        def _combined(state: str, message: str) -> None:
            internal_progress_cb(state, message)
            progress_cb(state, message)

        return execute_run_pipeline(
            question=inp.question,
            max_iterations=inp.max_iterations,
            output_dir=output_dir,
            data_dir=data_dir,
            deadline_sec=deadline_sec,
            stop_event=record.stop_event,
            progress_cb=_combined,
            scenario_id=inp.scenario_id,  # a2a/06
            project_id=inp.project_id,    # a2a/06
        )

    record = task_manager.submit(input_payload, _task_runner)
    # Блокирующее ожидание терминального статуса. ``future.result()`` отпускает,
    # когда задача финализирована (state in {completed, failed, canceled}).
    if record.future is not None:
        try:
            record.future.result()
        except Exception:
            # Исключение уже залогировано в TaskManager._start.
            pass
    # После завершения — обновляем record из стора.
    record = task_manager.get(record.task_id) or record
    return record.output or {
        "status": "failed",
        "error_code": "NO_OUTPUT",
        "error": "task finished without output",
    }


def _run_analyze_urban_question(
    input_payload: dict[str, Any],
    task_manager: Any,
    output_dir: Any,
    data_dir: Any,
    deadline_sec: int | None,
    progress_cb: Any,
) -> dict[str, Any]:
    """Реализация ``analyze_urban_question`` (back-compat).

    По сути — прокси для ``run_pipeline``. Никакой своей реализации pipeline
    (см. Q2): оба skill-а проходят через один ``execute_run_pipeline``.
    """
    inp = AnalyzeUrbanQuestionInput.model_validate(input_payload)
    # Преобразуем в ``RunPipelineInput`` (поля совпадают).
    return _run_run_pipeline(
        {
            "question": inp.question,
            "max_iterations": inp.max_iterations,
            "scenario_id": inp.scenario_id,
            "project_id": inp.project_id,
        },
        task_manager,
        output_dir,
        data_dir,
        deadline_sec,
        progress_cb,
    )


SKILLS: tuple[SkillSpec, ...] = (
    SkillSpec(
        id="run_pipeline",
        name="run_pipeline",
        description=(
            "Запускает полный аналитический конвейер BlocksNetAgent по "
            "городскому вопросу. Стримит статусы (submitted → working → "
            "completed/partial/failed), артефакты (карты, CSV), финальный "
            "JSON с гипотезами и рекомендациями."
        ),
        tags=("urban", "pipeline", "agent"),
        examples=(
            "Где в Кронштадте разместить новые спортивные площадки?",
            "Какие кварталы СПб имеют дефицит школ?",
        ),
        input_model=RunPipelineInput,
        runner=_run_run_pipeline,
    ),
    SkillSpec(
        id="analyze_urban_question",
        name="analyze_urban_question",
        description=(
            "[DEPRECATED] Back-compat обёртка над run_pipeline. "
            "Блокирующе ждёт терминального статуса. Используйте run_pipeline."
        ),
        tags=("urban", "legacy"),
        examples=("Где разместить новые школы?",),
        input_model=AnalyzeUrbanQuestionInput,
        runner=_run_analyze_urban_question,
    ),
)


def get_skill(skill_id: str) -> SkillSpec | None:
    for spec in SKILLS:
        if spec.id == skill_id:
            return spec
    return None


__all__ = ["SKILLS", "SkillSpec", "get_skill"]