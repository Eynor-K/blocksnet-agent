"""Контекст сценария (``ScenarioContext``) и его резолвер.

Шаг 06 a2a-рефакторинга. Используется и в MCP-сервере (привязка сессии к
сценарию), и в A2A-сервере (прокидывание ``scenario_id`` в ``AgentSettings``
конкретного прогона).

Источник истины по контракту — ``docs/mas_integration_implementation_plan.md``.

Главные свойства:
- Без ``scenario_id`` → дефолтные каталоги (``DATA_DIR``/``OUTPUT_DIR``).
  Текущее поведение сохраняется полностью.
- С ``scenario_id`` → ``DATA_DIR/<scenario_id>/``. Если каталога нет —
  материализация из UrbanDB (``URBANDB_URL``/``URBANDB_TOKEN``), при
  недоступности — ``SCENARIO_NOT_MATERIALIZED``.
- Валидация пути ОБЯЗАТЕЛЬНА: ``scenario_id`` приходит извне и попадает
  в путь. Без проверки — обход каталога. Защита двухуровневая:
  1. Регулярка ``[a-zA-Z0-9_-]{1,64}``.
  2. ``Path.resolve().is_relative_to(DATA_DIR.resolve())``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("blocksnet_agent.context")

# Whitelist для ``scenario_id``. Буквы/цифры/подчёркивание/дефис, 1-64 символа.
# Никаких ``/``, ``\``, ``.``, ``\x00`` и т.п.
_SCENARIO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Коды ошибок контекста.
ERROR_VALIDATION_ERROR = "VALIDATION_ERROR"
ERROR_SCENARIO_NOT_MATERIALIZED = "SCENARIO_NOT_MATERIALIZED"


class ContextError(Exception):
    """Ошибка резолвинга контекста с machine-readable code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class ScenarioContext:
    """Контекст сценария: разрешённые пути данных и вывода.

    Attributes:
        scenario_id: идентификатор сценария (``None`` → дефолт).
        project_id: идентификатор проекта в MAS (``None`` → без проекта).
        data_dir: разрешённый каталог данных (``DATA_DIR`` или ``DATA_DIR/<scenario_id>``).
        output_dir: каталог вывода (``OUTPUT_DIR``).
    """

    scenario_id: str | None
    project_id: str | None
    data_dir: Path
    output_dir: Path


def _validate_scenario_id(scenario_id: str | None) -> str | None:
    """Валидация ``scenario_id``: whitelist-регулярка.

    Raises:
        ContextError: с code=VALIDATION_ERROR, если id содержит запрещённые символы.
    """
    if scenario_id is None:
        return None
    if not isinstance(scenario_id, str) or not _SCENARIO_ID_PATTERN.match(scenario_id):
        raise ContextError(
            f"scenario_id must match [a-zA-Z0-9_-]{{1,64}}, got {scenario_id!r}",
            code=ERROR_VALIDATION_ERROR,
        )
    return scenario_id


def _safe_data_dir(scenario_id: str | None, data_dir: Path) -> Path:
    """Безопасное вычисление ``data_dir`` под scenario_id.

    Возвращает ``data_dir`` (если scenario_id is None) или ``data_dir/scenario_id``.
    Защита от path traversal: финальный путь должен быть внутри ``data_dir``.
    """
    base = data_dir.resolve()
    if scenario_id is None:
        return base
    candidate = (base / scenario_id).resolve()
    # Проверяем, что candidate — внутри base. ``is_relative_to`` (Python 3.9+)
    # даёт строгую проверку через сегменты пути.
    if not candidate.is_relative_to(base):
        # Не должно случаться после регулярки, но страховка.
        raise ContextError(
            f"scenario_id {scenario_id!r} resolves outside DATA_DIR",
            code=ERROR_VALIDATION_ERROR,
        )
    return candidate


def resolve_context(
    *,
    scenario_id: str | None,
    project_id: str | None,
    data_dir: Path,
    output_dir: Path,
    materializer: Any | None = None,
) -> ScenarioContext:
    """Резолвит ``ScenarioContext`` для прогона.

    Args:
        scenario_id: id сценария из auth-claims/tool-call (или None).
        project_id: id проекта (или None).
        data_dir: ``DATA_DIR`` из настроек.
        output_dir: ``OUTPUT_DIR`` из настроек.
        materializer: callable ``materializer(scenario_id, target_dir) -> None``
            (или None для отключения — кэш на диске + read-only). Вызывается,
            если ``target_dir`` не существует. По умолчанию — None
            (сценарий должен быть предварительно материализован).

    Returns:
        ``ScenarioContext`` с разрешёнными путями.

    Raises:
        ContextError: ``VALIDATION_ERROR`` (битый id) или
            ``SCENARIO_NOT_MATERIALIZED`` (нет каталога и materializer не помог).
    """
    safe_scenario = _validate_scenario_id(scenario_id)
    safe_project = _validate_scenario_id(project_id)  # project_id — те же правила

    target_data_dir = _safe_data_dir(safe_scenario, data_dir)
    if safe_scenario is not None and not target_data_dir.exists():
        if materializer is None:
            raise ContextError(
                f"scenario {safe_scenario!r} not materialized (no data at {target_data_dir})",
                code=ERROR_SCENARIO_NOT_MATERIALIZED,
            )
        try:
            materializer(safe_scenario, target_data_dir)
        except Exception as exc:  # noqa: BLE001
            log.exception("materializer failed for scenario %s", safe_scenario)
            raise ContextError(
                f"scenario {safe_scenario!r} materialization failed: {exc}",
                code=ERROR_SCENARIO_NOT_MATERIALIZED,
            ) from exc
        if not target_data_dir.exists():
            raise ContextError(
                f"scenario {safe_scenario!r} materialization did not produce data dir",
                code=ERROR_SCENARIO_NOT_MATERIALIZED,
            )

    return ScenarioContext(
        scenario_id=safe_scenario,
        project_id=safe_project,
        data_dir=target_data_dir,
        output_dir=output_dir.resolve(),
    )


def make_in_process_materializer(
    fetch_fn: Any | None = None,
) -> Any:
    """Фабрика materializer'а для тестов.

    Args:
        fetch_fn: callable ``fetch_fn(scenario_id, target_dir) -> None``.
            По умолчанию — просто ``mkdir(target_dir)`` (имитация).

    Returns:
        Callable ``materializer(scenario_id, target_dir)``.
    """

    def _materializer(scenario_id: str, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        if fetch_fn is not None:
            fetch_fn(scenario_id, target_dir)

    return _materializer


__all__ = [
    "ScenarioContext",
    "ContextError",
    "ERROR_VALIDATION_ERROR",
    "ERROR_SCENARIO_NOT_MATERIALIZED",
    "resolve_context",
    "make_in_process_materializer",
]