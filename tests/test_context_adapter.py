"""Тесты ``blocksnet_agent.context.resolve_context`` — резолвер сценария.

Шаг 06 a2a-рефакторинга. Главные гарантии:
- Без ``scenario_id`` → дефолтные каталоги (поведение не менялось).
- С ``scenario_id`` → ``data_dir/<scenario_id>/`` (если каталог есть).
- ``scenario_id="../../etc"`` → ``VALIDATION_ERROR``, файловая система не тронута.
- ``scenario_id="a/b"``, ``"a\\x00b"``, ``""``, длинный (>64) → отклонены.
- UrbanDB недоступна → ``SCENARIO_NOT_MATERIALIZED`` (через materializer).
- Повторный вызов не перекачивает данные (materializer вызывается один раз).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from blocksnet_agent.context import (
    ContextError,
    ERROR_SCENARIO_NOT_MATERIALIZED,
    ERROR_VALIDATION_ERROR,
    make_in_process_materializer,
    resolve_context,
)


# --- дефолтное поведение ---------------------------------------------------


def test_default_no_scenario_returns_base_dirs(tmp_path: Path) -> None:
    """Без ``scenario_id`` — дефолтные каталоги (без подкаталога)."""
    data = tmp_path / "data"
    out = tmp_path / "out"
    ctx = resolve_context(
        scenario_id=None,
        project_id=None,
        data_dir=data,
        output_dir=out,
    )
    assert ctx.scenario_id is None
    assert ctx.project_id is None
    assert ctx.data_dir == data.resolve()
    assert ctx.output_dir == out.resolve()


def test_existing_scenario_resolves_to_subdir(tmp_path: Path) -> None:
    """С существующим подкаталогом — возвращает его как data_dir."""
    data = tmp_path / "data"
    scenario_dir = data / "spb_2024"
    scenario_dir.mkdir(parents=True)

    ctx = resolve_context(
        scenario_id="spb_2024",
        project_id=None,
        data_dir=data,
        output_dir=tmp_path / "out",
    )
    assert ctx.scenario_id == "spb_2024"
    assert ctx.data_dir == scenario_dir.resolve()


def test_output_dir_unchanged_with_scenario(tmp_path: Path) -> None:
    """``output_dir`` НЕ подкаталогизируется по scenario_id (там копятся run_*)."""
    data = tmp_path / "data"
    (data / "x").mkdir(parents=True)
    out = tmp_path / "out"
    ctx = resolve_context(
        scenario_id="x",
        project_id=None,
        data_dir=data,
        output_dir=out,
    )
    assert ctx.output_dir == out.resolve()


# --- валидация -------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "../etc",
        "../../etc/passwd",
        "a/b",
        "a\\b",
        "a\x00b",
        "",
        "a" * 65,  # >64
        "has spaces",
        "has.dots",
        "id;rm",
    ],
)
def test_invalid_scenario_id_rejected(
    tmp_path: Path, bad_id: str
) -> None:
    """Path traversal и спецсимволы — ``VALIDATION_ERROR``."""
    with pytest.raises(ContextError) as exc_info:
        resolve_context(
            scenario_id=bad_id,
            project_id=None,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
        )
    assert exc_info.value.code == ERROR_VALIDATION_ERROR


def test_invalid_scenario_id_does_not_modify_filesystem(tmp_path: Path) -> None:
    """Path traversal НЕ должен создать файлы вне DATA_DIR."""
    data = tmp_path / "data"
    data.mkdir()
    try:
        resolve_context(
            scenario_id="../../etc",
            project_id=None,
            data_dir=data,
            output_dir=tmp_path / "out",
        )
    except ContextError:
        pass
    # ``etc`` НЕ должен появиться внутри ``data`` или вообще.
    assert not (tmp_path / "etc").exists()
    assert list(data.iterdir()) == []  # ничего не создано


# --- материализация -------------------------------------------------------


def test_missing_scenario_raises_without_materializer(tmp_path: Path) -> None:
    """Сценарий не существует и materializer=None → ``SCENARIO_NOT_MATERIALIZED``."""
    with pytest.raises(ContextError) as exc_info:
        resolve_context(
            scenario_id="ghost",
            project_id=None,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
        )
    assert exc_info.value.code == ERROR_SCENARIO_NOT_MATERIALIZED


def test_missing_scenario_with_materializer(tmp_path: Path) -> None:
    """С materializer — каталог создаётся, контекст возвращается."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    calls: list[str] = []

    def fetch(scenario_id: str, target_dir: Path) -> None:
        calls.append(scenario_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "marker.txt").write_text("ok")

    ctx = resolve_context(
        scenario_id="alpha",
        project_id=None,
        data_dir=data,
        output_dir=tmp_path / "out",
        materializer=make_in_process_materializer(fetch_fn=fetch),
    )
    assert ctx.scenario_id == "alpha"
    assert (ctx.data_dir / "marker.txt").exists()
    assert calls == ["alpha"]


def test_repeated_call_does_not_re_materialize(tmp_path: Path) -> None:
    """Повторный вызов с уже существующим сценарием НЕ дёргает materializer."""
    data = tmp_path / "data"
    (data / "beta").mkdir(parents=True, exist_ok=True)
    calls: list[str] = []

    def fetch(scenario_id: str, target_dir: Path) -> None:
        calls.append(scenario_id)

    # Первый вызов — materializer не нужен (каталог уже есть).
    resolve_context(
        scenario_id="beta",
        project_id=None,
        data_dir=data,
        output_dir=tmp_path / "out",
        materializer=make_in_process_materializer(fetch_fn=fetch),
    )
    # Второй вызов — тоже без материализации.
    resolve_context(
        scenario_id="beta",
        project_id=None,
        data_dir=data,
        output_dir=tmp_path / "out",
        materializer=make_in_process_materializer(fetch_fn=fetch),
    )
    assert calls == [], "materializer НЕ должен вызываться для существующих сценариев"


def test_materializer_failure_raises(tmp_path: Path) -> None:
    """Если materializer бросил — ``SCENARIO_NOT_MATERIALIZED`` (не голое исключение)."""

    def boom(scenario_id: str, target_dir: Path) -> None:
        raise ConnectionError("urbandb down")

    with pytest.raises(ContextError) as exc_info:
        resolve_context(
            scenario_id="needs-urbandb",
            project_id=None,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
            materializer=make_in_process_materializer(fetch_fn=boom),
        )
    assert exc_info.value.code == ERROR_SCENARIO_NOT_MATERIALIZED
    assert "urbandb down" in str(exc_info.value)


# --- project_id -----------------------------------------------------------


def test_project_id_validation(tmp_path: Path) -> None:
    """project_id валидируется по тем же правилам, что и scenario_id."""
    with pytest.raises(ContextError) as exc_info:
        resolve_context(
            scenario_id=None,
            project_id="../../etc",
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
        )
    assert exc_info.value.code == ERROR_VALIDATION_ERROR


def test_project_id_passes_through(tmp_path: Path) -> None:
    """Валидный project_id сохраняется в контексте."""
    ctx = resolve_context(
        scenario_id=None,
        project_id="proj_42",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "out",
    )
    assert ctx.project_id == "proj_42"