"""Хранилище сессий MCP: session_id -> изолированный state инструментов.

Шаг 02 a2a-рефакторинга. Проблема, которую это решает:

- Инструменты BlocksNetAgent не stateless. ``load_blocks()`` кладёт GeoDataFrame в state,
  ``compute_service_provision("school")`` — результат в state["provision_school"], а
  ``get_analysis_results()``/``get_metric_for_block()``/``render_metric_map()``/
  ``list_cached_data()`` его оттуда ЧИТАЮТ.
- Если MCP-сервер создаст один ``state`` на процесс — два параллельных клиента затрут
  данные друг друга.
- Если создавать ``state`` на каждый вызов — многошаговые сценарии не работают
  («Кэш пуст. Загрузи данные с помощью load_blocks()»).

Решение — ``session_id``: явный идентификатор сессии, который клиент передаёт
в каждый tool-call. ``SessionStore`` гарантирует изоляцию state между сессиями.

Шаг 06: сессия привязывается к ``scenario_id``/``project_id`` (``Session.meta``).
Это позволяет инструментам в сессии работать с материализованным подсценарием
(``data_dir/<scenario_id>``) без передачи scenario_id в каждом вызове.

Граница ответственности:
- Хранилище — **только в памяти процесса** (Q4, ограничение v2.0).
- TTL и LRU — защита от OOM (GeoDataFrame кварталов + матрица доступности = сотни МБ).
- Артефакты инструментов — на диске в OUTPUT_DIR, а не в state.
- Сценарий привязан к сессии один раз. Смена ``scenario_id`` в существующей
  сессии — ошибка ``SESSION_SCENARIO_MISMATCH`` (защита от случайного микс-а
  данных разных сценариев).

Что НЕ хранится здесь:
- LLM-контекст, история вызовов, прогресс — это в ``blocksnet_agent.runtime``.
- Авторизация и проверка токена — это в ``blocksnet_mcp.auth``/``blocksnet_agent.authcore``.
- Резолвинг сценария (``data_dir``) — это в ``blocksnet_agent.context`` (но
  ``data_dir`` сессии фиксируется при ``open_session``).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from blocksnet_mcp.settings import get_mcp_settings

# Имя «дефолтной» сессии. Однопользовательский сценарий без изменений у клиента:
# все вызовы без session_id и с session_id="default" идут в одну и ту же сессию.
DEFAULT_SESSION_ID = "default"

# Код ошибки при попытке сменить scenario_id у существующей сессии.
ERROR_SESSION_SCENARIO_MISMATCH = "SESSION_SCENARIO_MISMATCH"


class SessionScenarioMismatch(Exception):
    """Поднят при попытке сменить scenario_id в существующей сессии.

    Код ошибки — ``ERROR_SESSION_SCENARIO_MISMATCH``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = ERROR_SESSION_SCENARIO_MISMATCH


@dataclass
class Session:
    """Изолированный контекст для одного клиента MCP.

    ``state`` — тот же ``dict``, что передаётся в ``make_tools(state, ...)``.
    ``meta`` — служебные поля (scenario_id/project_id — заполняются на шаге 06).
    ``data_dir``/``output_dir`` — фиксируются при создании, чтобы смена
    глобальных настроек не ломала уже открытую сессию.
    """

    session_id: str
    state: dict[str, Any] = field(default_factory=dict)
    data_dir: Path | None = None
    output_dir: Path | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    meta: dict[str, Any] = field(default_factory=dict)


def _new_session_id() -> str:
    """Генерация нового id: короткий, читаемый, безопасный для логов."""
    return f"s-{uuid.uuid4().hex[:8]}"


class SessionStore:
    """Хранилище сессий: session_id -> Session.

    Все публичные методы потокобезопасны (RLock). Это важно: FastMCP исполняет
    инструменты в пуле потоков, без локов параллельные клиенты затрют state.

    Параметры:
        ttl_sec: время жизни сессии с последнего использования (default 1800s = 30min).
        max_sessions: лимит одновременно живых сессий (default 8). При превышении —
            вытесняется самая старая по ``last_used_at``, кроме ``"default"``.
    """

    def __init__(self, ttl_sec: float = 1800.0, max_sessions: int = 8) -> None:
        if ttl_sec <= 0:
            raise ValueError(f"ttl_sec must be > 0, got {ttl_sec}")
        if max_sessions <= 0:
            raise ValueError(f"max_sessions must be > 0, got {max_sessions}")
        self._ttl_sec = ttl_sec
        self._max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    # --- основные операции ---------------------------------------------------

    def get_or_create(
        self,
        session_id: str | None,
        *,
        scenario_id: str | None = None,
        project_id: str | None = None,
        data_dir: Path | None = None,
        output_dir: Path | None = None,
    ) -> Session:
        """Получить существующую сессию или создать новую.

        ``None`` и ``"default"`` нормализуются к ``DEFAULT_SESSION_ID`` —
        однопользовательский сценарий остаётся без изменений.
        Перед созданием вызывается ``sweep()`` — протухшие сессии удаляются.
        При превышении ``max_sessions`` — вытесняется самая старая (LRU).

        Args:
            session_id: id сессии (или None → "default").
            scenario_id: id сценария (привязывается к сессии при создании).
                None → дефолтный сценарий (без подкаталога).
            project_id: id проекта (опционально).
            data_dir: разрешённый каталог данных (фиксируется в сессии).
            output_dir: каталог вывода (фиксируется в сессии).

        Raises:
            SessionScenarioMismatch: если сессия уже существует с другим
                scenario_id (защита от микс-а данных разных сценариев).
        """
        sid = self._normalize_id(session_id)
        with self._lock:
            self.sweep()
            existing = self._sessions.get(sid)
            if existing is not None:
                # Сессия существует — проверить совпадение scenario_id.
                # ``None`` (default) совместим с любым scenario_id (старый код-путь
                # продолжает работать); явное несовпадение → ошибка.
                existing_scenario = existing.meta.get("scenario_id")
                if (
                    existing_scenario is not None
                    and scenario_id is not None
                    and existing_scenario != scenario_id
                ):
                    raise SessionScenarioMismatch(
                        f"session {sid!r} bound to scenario {existing_scenario!r}, "
                        f"refusing to switch to {scenario_id!r}",
                    )
                existing.last_used_at = time.monotonic()
                return existing
            # Перед созданием новой — вытеснение, если лимит.
            self._evict_if_needed(protected=sid)
            new_session = Session(
                session_id=sid,
                data_dir=data_dir,
                output_dir=output_dir,
                meta={"scenario_id": scenario_id, "project_id": project_id},
            )
            self._sessions[sid] = new_session
            return new_session

    def get(self, session_id: str) -> Session | None:
        """Получить сессию по id без создания. Возвращает ``None``, если нет."""
        sid = self._normalize_id(session_id)
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return None
            # Даже ``get`` обновляет last_used — сессия не считается протухшей,
            # пока к ней обращаются.
            session.last_used_at = time.monotonic()
            return session

    def close(self, session_id: str) -> bool:
        """Закрыть сессию: ``state.clear()`` + удаление из стора.

        ``state.clear()`` нужен явно: GeoDataFrame'ы держат большие буферы,
        GC может задержать освобождение. Возвращает ``True``, если сессия была.
        """
        sid = self._normalize_id(session_id)
        with self._lock:
            session = self._sessions.pop(sid, None)
            if session is None:
                return False
            session.state.clear()
            session.meta.clear()
            return True

    def sweep(self) -> int:
        """Удаляет сессии, у которых ``idle_sec > ttl_sec``. Возвращает число удалённых.

        Вызывается автоматически в ``get_or_create``. Можно дёргать вручную
        (например, из фонового таска очистки) — идемпотентно.
        """
        now = time.monotonic()
        with self._lock:
            expired = [
                sid
                for sid, session in self._sessions.items()
                if now - session.last_used_at > self._ttl_sec
            ]
            for sid in expired:
                self._sessions.pop(sid, None)
                # state уже освобождён через close() — здесь только pop.
            return len(expired)

    def info(self, session_id: str | None = None) -> dict[str, Any]:
        """Диагностика: список сессий или детали одной.

        ``keys`` — только имена ключей в state (без значений, там могут быть
        DataFrame'ы). ``None`` — диагностика всего стора.
        """
        with self._lock:
            if session_id is None:
                return {
                    "ttl_sec": self._ttl_sec,
                    "max_sessions": self._max_sessions,
                    "n_sessions": len(self._sessions),
                    "sessions": [
                        {
                            "session_id": s.session_id,
                            "age_sec": time.monotonic() - s.created_at,
                            "idle_sec": time.monotonic() - s.last_used_at,
                            "n_keys": len(s.state),
                            "keys": list(s.state.keys()),
                        }
                        for s in self._sessions.values()
                    ],
                }
            sid = self._normalize_id(session_id)
            session = self._sessions.get(sid)
            if session is None:
                return {"session_id": sid, "exists": False}
            return {
                "session_id": session.session_id,
                "age_sec": time.monotonic() - session.created_at,
                "idle_sec": time.monotonic() - session.last_used_at,
                "n_keys": len(session.state),
                "keys": list(session.state.keys()),
                "meta": dict(session.meta),
            }

    # --- внутренние хелперы --------------------------------------------------

    def _normalize_id(self, session_id: str | None) -> str:
        """``None`` и пустая строка → DEFAULT_SESSION_ID."""
        if not session_id:
            return DEFAULT_SESSION_ID
        return session_id

    def _evict_if_needed(self, protected: str) -> None:
        """LRU-вытеснение: закрыть самую старую сессию, кроме ``protected`` и ``"default"``."""
        if len(self._sessions) < self._max_sessions:
            return
        # Сортируем по last_used_at, исключая protected и DEFAULT.
        candidates = [
            (sid, s)
            for sid, s in self._sessions.items()
            if sid != protected and sid != DEFAULT_SESSION_ID
        ]
        if not candidates:
            # Все сессии — protected/default, ничего не вытесняем.
            return
        oldest_sid, oldest = min(candidates, key=lambda item: item[1].last_used_at)
        self._sessions.pop(oldest_sid, None)
        oldest.state.clear()
        oldest.meta.clear()


# --- синглтон ---------------------------------------------------------------


@lru_cache(maxsize=1)
def get_session_store() -> SessionStore:
    """Глобальный синглтон SessionStore, читает TTL/лимит из настроек."""
    settings = get_mcp_settings()
    return SessionStore(ttl_sec=settings.session_ttl_sec, max_sessions=settings.max_sessions)


def reset_session_store() -> None:
    """Сбрасывает lru_cache для ``get_session_store()``. Используется в тестах."""
    get_session_store.cache_clear()


__all__ = [
    "DEFAULT_SESSION_ID",
    "Session",
    "SessionStore",
    "SessionScenarioMismatch",
    "ERROR_SESSION_SCENARIO_MISMATCH",
    "get_session_store",
    "reset_session_store",
]