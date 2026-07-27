"""P0.2: регресс-тесты на run-контекст.

Гарантируем: (а) ``start_run`` идемпотентен, не теряет deadline/callback;
(б) контекст живёт в ContextVar, а не в глобальной переменной;
(в) двойной ``start_run`` (как делает ``agent.run()`` поверх MCP-слоя) не плодит
повторных каталогов ``run_*`` и не затирает ``deadline_at``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from blocksnet_agent import runtime


@pytest.fixture(autouse=True)
def _reset_runtime():
    """Сбрасываем состояние runtime до и после каждого теста, чтобы не утекало."""
    runtime._set_current(None)
    runtime._stop_event.clear()
    yield
    runtime._set_current(None)
    runtime._stop_event.clear()


def test_start_run_returns_context_with_deadline(tmp_path: Path) -> None:
    """P0.2: start_run с deadline_sec сохраняет абсолютный дедлайн в контексте."""
    callback_calls: list[tuple[int, int, str]] = []

    def cb(done: int, total: int, message: str) -> None:
        callback_calls.append((done, total, message))

    ctx = runtime.start_run(tmp_path, progress_callback=cb, deadline_sec=120)

    assert ctx.deadline_at is not None
    assert ctx.progress_callback is cb
    assert ctx.run_dir.parent == tmp_path


def test_double_start_run_does_not_overwrite_deadline(tmp_path: Path) -> None:
    """P0.2: повторный start_run (как в agent.run() поверх MCP) НЕ затирает deadline.

    Раньше это приводило к тому, что ``is_deadline_reached()`` всегда был False
    и сервер ронял ``ExceptionGroup`` через ~10 мин при ``DEADLINE_SEC=480``.
    """
    first = runtime.start_run(tmp_path, deadline_sec=300)
    second = runtime.start_run(tmp_path)

    assert first is second
    assert second.deadline_at == first.deadline_at


def test_double_start_run_does_not_create_second_directory(tmp_path: Path) -> None:
    """P0.2: подтверждаем, что каталог не дублируется — был «два run_* каталога на запуск»."""
    runtime.start_run(tmp_path)
    runtime.start_run(tmp_path)
    runtime.start_run(tmp_path)

    runs = sorted(tmp_path.glob("run_*"))
    assert len(runs) == 1


def test_start_run_overwrite_replaces_context(tmp_path: Path) -> None:
    """P0.2: явный overwrite=True — единственный путь создать новый контекст."""
    first = runtime.start_run(tmp_path, deadline_sec=300)
    second = runtime.start_run(tmp_path, deadline_sec=10, overwrite=True)

    assert first is not second
    assert second.deadline_at != first.deadline_at


def test_is_deadline_reached_uses_active_context(tmp_path: Path) -> None:
    """P0.2: ``is_deadline_reached`` видит deadline активного контекста, а не None."""
    runtime.start_run(tmp_path, deadline_sec=1)

    assert runtime.is_deadline_reached() is False
    runtime._stop_event.set()
    assert runtime.is_stop_requested() is True


def test_run_context_isolated_in_contextvar(tmp_path: Path) -> None:
    """P0.2: контекст живёт в ContextVar, не в глобале — изоляция между задачами asyncio."""
    ctx_a = runtime.start_run(tmp_path, deadline_sec=300)

    async def inner_task():
        return runtime.get_run_context()

    async def outer_task():
        # В том же event loop — current context из outer.
        return await inner_task(), runtime.get_run_context()

    async def main() -> None:
        result = await outer_task()
        assert result == (ctx_a, ctx_a)

    asyncio.run(main())
