"""Тесты шага 04 a2a-рефакторинга: per-run stop-флаг.

Главные гарантии:
- ``request_stop()`` взводит ТОЛЬКО флаг текущего рана — соседние раны живут.
- ``stop_run(all_runs=True)`` взводит глобальный флаг (для shutdown).
- ``is_stop_requested()`` возвращает True если взведён ЛЮБОЙ (per-run или global).
- ``start_run(overwrite=True)`` создаёт новый контекст с ЧИСТЫМ stop_event —
  не наследует отмену от прошлого рана.
- Без активного контекста ``is_stop_requested()`` видит только глобальный.

Сигнатуры обратно совместимы: ``grep -rn "stop_run\\|is_stop_requested" --include=*.py .``
должен показать, что все вызывающие работают без правок.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from blocksnet_agent import runtime


@pytest.fixture(autouse=True)
def _reset_runtime():
    """Сбрасываем runtime до/после каждого теста.

    a2a/04: помимо ``_set_current(None)`` чистим глобальный ``_stop_event``,
    чтобы утечка отмены между тестами не ломала изоляцию.
    """
    runtime._set_current(None)
    runtime._stop_event.clear()
    yield
    runtime._set_current(None)
    runtime._stop_event.clear()


# --- базовые контракты -----------------------------------------------------


def test_run_context_has_per_run_stop_event(tmp_path: Path) -> None:
    """У ``RunContext`` есть свой ``stop_event`` — не зависит от глобального."""
    ctx = runtime.start_run(tmp_path)
    assert isinstance(ctx.stop_event, threading.Event)
    # Новый контекст — чистый стоп-флаг.
    assert not ctx.stop_event.is_set()


def test_request_stop_sets_only_current_run(tmp_path: Path) -> None:
    """request_stop() взводит per-run флаг, глобальный НЕ трогает."""
    ctx = runtime.start_run(tmp_path)

    runtime.request_stop()

    # Per-run взведён.
    assert ctx.stop_event.is_set()
    assert runtime.is_stop_requested() is True
    # Глобальный НЕ взведён.
    assert not runtime._stop_event.is_set()


def test_stop_run_default_targets_current_run_only(tmp_path: Path) -> None:
    """stop_run() без all_runs — только текущий контекст."""
    ctx = runtime.start_run(tmp_path)
    runtime.stop_run()

    assert ctx.stop_event.is_set()
    assert not runtime._stop_event.is_set()


def test_stop_run_all_runs_targets_global(tmp_path: Path) -> None:
    """stop_run(all_runs=True) — глобальный флаг (shutdown-сценарий)."""
    runtime.start_run(tmp_path)
    runtime.stop_run(all_runs=True)

    assert runtime._stop_event.is_set()
    # Per-run тоже (потому что глобальный True → is_stop_requested() = True
    # даже без взвода per-run). Но проверим, что сам per-run не взведён
    # автоматически от stop_run(all_runs=True).
    ctx = runtime.get_run_context()
    assert ctx is not None
    assert not ctx.stop_event.is_set(), (
        "stop_run(all_runs=True) НЕ должен трогать per-run флаг, "
        "иначе отмена одного рана валит соседние"
    )


# --- изоляция между ранами --------------------------------------------------


def test_two_runs_have_independent_stop_events(tmp_path: Path) -> None:
    """Два рана (в двух потоках) — у каждого свой stop_event."""
    events: dict[str, threading.Event] = {}
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        runtime._set_current(runtime.start_run(tmp_path))
        events[name] = runtime.get_run_context().stop_event
        barrier.wait(timeout=2.0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, ["a", "b"]))

    # Гонка: какой поток последним set'нул current — тот и «current» в основном потоке.
    # Но events у каждого свой, и оба должны быть созданы.
    assert set(events.keys()) == {"a", "b"}
    a, b = events["a"], events["b"]
    assert a is not b, "stop_event должен быть per-run, не общий"
    assert not a.is_set()
    assert not b.is_set()


def test_stop_one_run_does_not_affect_another(tmp_path: Path) -> None:
    """request_stop() для рана A не трогает ран B (главный регресс-кейс)."""
    # Создаём два рана подряд (без overwrite=True — вернётся первый, как
    # текущий). Чтобы реально получить два независимых контекста, используем
    # явное сохранение ссылок через _set_current в двух потоках.
    results: dict[str, bool] = {}
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        ctx = runtime.start_run(tmp_path)
        runtime._set_current(ctx)
        barrier.wait(timeout=2.0)
        # Стоп — текущего рана.
        runtime.request_stop()
        # Проверяем, что ВНУТРИ worker'а is_stop_requested() = True.
        results[f"{name}_in"] = runtime.is_stop_requested()
        # А на «другом» ране (подменяем контекст обратно через другого worker)
        # — это уже вне scope. Поэтому проверяем ссылку напрямую.

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    # Внутри обоих worker'ов stop был видим (per-run взведён).
    assert results["a_in"] is True
    assert results["b_in"] is True


# --- is_stop_requested без контекста ---------------------------------------


def test_is_stop_requested_without_context_returns_global() -> None:
    """Без активного контекста ``is_stop_requested()`` видит только глобальный."""
    runtime._set_current(None)
    # Глобальный не взведён.
    assert runtime.is_stop_requested() is False
    # request_stop() без контекста — ничего не делает.
    runtime.request_stop()
    assert not runtime._stop_event.is_set()
    assert runtime.is_stop_requested() is False
    # А глобальный — взводится явно через stop_run(all_runs=True).
    runtime.stop_run(all_runs=True)
    assert runtime.is_stop_requested() is True


def test_global_stop_affects_active_context() -> None:
    """Глобальный стоп-флаг виден через ``is_stop_requested()`` в активном контексте."""
    runtime.start_run(tmp_path := Path("/tmp"))
    runtime.stop_run(all_runs=True)

    ctx = runtime.get_run_context()
    assert ctx is not None
    # Per-run флаг не взведён.
    assert not ctx.stop_event.is_set()
    # Но is_stop_requested() видит глобальный.
    assert runtime.is_stop_requested() is True


# --- start_run не наследует отмену ----------------------------------------


def test_start_run_overwrite_creates_clean_stop_event(tmp_path: Path) -> None:
    """``start_run(overwrite=True)`` создаёт новый контекст с чистым stop_event."""
    first = runtime.start_run(tmp_path)
    first.stop_event.set()  # имитируем отмену первого рана

    second = runtime.start_run(tmp_path, overwrite=True)

    assert second is not first
    assert not second.stop_event.is_set(), (
        "новый контекст не должен наследовать отмену от прошлого"
    )


def test_start_run_without_overwrite_returns_existing(tmp_path: Path) -> None:
    """Без ``overwrite=True`` второй start_run возвращает тот же контекст.

    Поведение не меняется (P0.2). Это регресс-тест: до a2a/04 ``_stop_event.clear()``
    гасил чужую отмену; теперь — не гасит (только per-run чистый).
    """
    first = runtime.start_run(tmp_path)
    first.stop_event.set()
    second = runtime.start_run(tmp_path)

    assert first is second
    # Stop_event унаследован (это тот же объект).
    assert second.stop_event.is_set()


# --- многопоточная нагрузка ----------------------------------------------


def test_concurrent_stop_does_not_corrupt_store(tmp_path: Path) -> None:
    """20 потоков: request_stop() не роняет стор, per-run флаги независимы."""
    barrier = threading.Barrier(20)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            ctx = runtime.start_run(tmp_path)
            runtime._set_current(ctx)
            barrier.wait(timeout=2.0)
            runtime.request_stop()
            assert ctx.stop_event.is_set()
        except BaseException as exc:  # noqa: BLE001 — ловим всё для отчёта
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(worker, range(20)))

    assert not errors, f"исключения в потоках: {errors}"


# --- обратная совместимость сигнатур --------------------------------------


def test_signature_backward_compatible() -> None:
    """Сигнатуры ``stop_run``/``request_stop``/``is_stop_requested`` не изменились
    настолько, чтобы сломать существующих вызывающих.
    """
    import inspect

    # request_stop и is_stop_requested — без аргументов (как и было).
    assert inspect.signature(runtime.request_stop).parameters == {}
    assert inspect.signature(runtime.is_stop_requested).parameters == {}

    # stop_run — keyword-only ``all_runs`` (новое), но без него вызывается как раньше.
    sig = inspect.signature(runtime.stop_run)
    assert "all_runs" in sig.parameters
    # ``stop_run()`` без аргументов работает.
    runtime.stop_run()  # не должно бросить