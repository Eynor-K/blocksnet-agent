"""Тесты связки MCP-сессий и сценариев (шаг 06).

Главные гарантии:
- Сессия привязывается к ``scenario_id`` через ``open_session(scenario_id=...)``.
- Смена ``scenario_id`` в существующей сессии → ``SESSION_SCENARIO_MISMATCH``.
- ``data_dir`` сессии — путь к материализованному сценарию.
- ``scenario_id=None`` совместим с любым (default-сессия).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from blocksnet_mcp.session import (
    SessionScenarioMismatch,
    SessionStore,
)


@pytest.fixture
def data_dir_with_scenario(tmp_path: Path) -> Path:
    """DATA_DIR с двумя материализованными сценариями."""
    data = tmp_path / "data"
    (data / "scenario_a").mkdir(parents=True)
    (data / "scenario_b").mkdir(parents=True)
    return data


def test_session_stores_scenario_id_in_meta(
    data_dir_with_scenario: Path,
) -> None:
    """``scenario_id`` сохраняется в ``session.meta``."""
    store = SessionStore()
    session = store.get_or_create(
        "s1",
        scenario_id="scenario_a",
        data_dir=data_dir_with_scenario / "scenario_a",
    )
    assert session.meta.get("scenario_id") == "scenario_a"


def test_session_data_dir_is_scenario_subdir(
    data_dir_with_scenario: Path,
) -> None:
    """``session.data_dir`` указывает на подкаталог сценария."""
    store = SessionStore()
    scenario_dir = data_dir_with_scenario / "scenario_b"
    session = store.get_or_create(
        "s2",
        scenario_id="scenario_b",
        data_dir=scenario_dir,
    )
    assert session.data_dir == scenario_dir


def test_change_scenario_in_existing_session_raises_mismatch(
    data_dir_with_scenario: Path,
) -> None:
    """Смена ``scenario_id`` в существующей сессии → ``SESSION_SCENARIO_MISMATCH``."""
    store = SessionStore()
    # Создаём сессию с scenario_a.
    store.get_or_create(
        "shared",
        scenario_id="scenario_a",
        data_dir=data_dir_with_scenario / "scenario_a",
    )
    # Попытка переключиться на scenario_b → ошибка.
    with pytest.raises(SessionScenarioMismatch) as exc_info:
        store.get_or_create(
            "shared",
            scenario_id="scenario_b",
            data_dir=data_dir_with_scenario / "scenario_b",
        )
    assert exc_info.value.code == "SESSION_SCENARIO_MISMATCH"


def test_same_scenario_id_in_existing_session_ok(
    data_dir_with_scenario: Path,
) -> None:
    """Тот же ``scenario_id`` — сессия возвращается, ошибки нет."""
    store = SessionStore()
    first = store.get_or_create(
        "shared",
        scenario_id="scenario_a",
        data_dir=data_dir_with_scenario / "scenario_a",
    )
    second = store.get_or_create(
        "shared",
        scenario_id="scenario_a",
        data_dir=data_dir_with_scenario / "scenario_a",
    )
    assert first is second


def test_default_session_accepts_any_scenario_id(
    data_dir_with_scenario: Path,
) -> None:
    """``scenario_id=None`` (default) — совместим с любым scenario_id.

    Старые клиенты без ``scenario_id`` продолжают работать.
    """
    store = SessionStore()
    first = store.get_or_create("legacy")  # без scenario_id
    # С scenario_id=None второй вызов — та же сессия.
    second = store.get_or_create("legacy", scenario_id=None)
    assert first is second


def test_existing_default_session_accepts_scenario_id(
    data_dir_with_scenario: Path,
) -> None:
    """``scenario_id=None`` при создании → потом можно передать ``scenario_id``
    без mismatch (default-сессия совместима).
    """
    store = SessionStore()
    # Создаём без scenario_id.
    first = store.get_or_create("legacy")
    # Получаем с scenario_id — должно вернуть ту же сессию (default совместим).
    second = store.get_or_create(
        "legacy",
        scenario_id="scenario_a",
        data_dir=data_dir_with_scenario / "scenario_a",
    )
    assert first is second


def test_session_meta_default_is_empty_dict() -> None:
    """Дефолтная сессия без scenario_id: ``meta`` инициализируется пустым dict
    с ключами scenario_id/project_id=None (фиксированный контракт для чтения)."""
    store = SessionStore()
    session = store.get_or_create("empty")
    assert isinstance(session.meta, dict)
    assert session.meta.get("scenario_id") is None
    assert session.meta.get("project_id") is None


def test_mismatch_error_has_correct_code() -> None:
    """``SessionScenarioMismatch.code = SESSION_SCENARIO_MISMATCH``."""
    err = SessionScenarioMismatch("test message")
    assert err.code == "SESSION_SCENARIO_MISMATCH"
    assert "test message" in err.message