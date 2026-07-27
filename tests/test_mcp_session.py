"""Тесты для ``blocksnet_mcp.session``.

Шаг 02 a2a-рефакторинга. Покрывает:
- Изоляцию state между сессиями (главное назначение стора).
- TTL-протухание (через ``time.monotonic``, не системные часы).
- LRU-вытеснение с защитой ``"default"``-сессии.
- ``close()`` действительно освобождает state (не только удаляет из стора).
- ``info()`` не утекает содержимым state — только имена ключей.
- Потокобезопасность под нагрузкой 20 одновременных ``get_or_create``.
- Граничные значения конструктора (ttl_sec <= 0 / max_sessions <= 0 → ValueError).
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from blocksnet_mcp.session import (
    DEFAULT_SESSION_ID,
    Session,
    SessionStore,
    get_session_store,
    reset_session_store,
)


# --- фикстуры ---------------------------------------------------------------


@pytest.fixture
def store() -> SessionStore:
    """Свежий стор для каждого теста — изоляция между кейсами."""
    return SessionStore(ttl_sec=60.0, max_sessions=8)


# --- базовые контракты ------------------------------------------------------


def test_default_session_is_stable(store: SessionStore) -> None:
    """``None`` и ``"default"`` дают одну и ту же сессию — однопользовательский путь."""
    assert store.get_or_create(None) is store.get_or_create("default")
    # И второй ``None`` тоже.
    assert store.get_or_create(None) is store.get_or_create(None)


def test_explicit_session_id_returns_same(store: SessionStore) -> None:
    """Один и тот же id → одна и та же сессия, last_used_at обновляется."""
    s1 = store.get_or_create("user-42")
    s2 = store.get_or_create("user-42")
    assert s1 is s2
    assert s2.last_used_at >= s1.last_used_at


def test_new_session_id_has_prefix() -> None:
    """Свежий id (явно не default) имеет формат ``s-<8 hex>``."""
    store = SessionStore()
    # Передаём None → будет "default", не подходит. Передаём что-то ещё →
    # первый раз создаст новую сессию.
    s = store.get_or_create("user-fresh-1")
    assert s.session_id == "user-fresh-1", "явный id должен сохраняться как есть"
    # Для генерации нового id нужен явный вызов с уникальным id; проверим формат
    # через приватную функцию.
    from blocksnet_mcp.session import _new_session_id

    new_id = _new_session_id()
    assert new_id.startswith("s-")
    assert len(new_id) == 10
    int(new_id[2:], 16)  # hex, без 's-'


def test_default_session_is_default_id(store: SessionStore) -> None:
    """``None`` нормализуется в ``"default"`` — это имя, а не сгенерированный id."""
    s = store.get_or_create(None)
    assert s.session_id == DEFAULT_SESSION_ID
    assert s.session_id == "default"


# --- изоляция ---------------------------------------------------------------


def test_sessions_are_isolated(store: SessionStore) -> None:
    """state одной сессии не виден другой — главный инвариант."""
    a = store.get_or_create("a")
    b = store.get_or_create("b")
    a.state["blocks"] = "X"
    a.state["provision_school"] = {"rows": 12}
    assert "blocks" not in b.state
    assert "provision_school" not in b.state
    # И наоборот: запись в b не утекает в a.
    b.state["foo"] = 1
    assert "foo" not in a.state


def test_state_independent_between_get_calls(store: SessionStore) -> None:
    """Каждый ``get_or_create`` возвращает тот же объект (не копию)."""
    s1 = store.get_or_create("x")
    s2 = store.get_or_create("x")
    s1.state["k"] = 1
    assert s2.state["k"] == 1


# --- TTL --------------------------------------------------------------------


def test_ttl_expires_session() -> None:
    """По истечении TTL сессия удаляется через ``sweep()``."""
    store = SessionStore(ttl_sec=0.01)
    sid = store.get_or_create(None).session_id
    assert store.get(sid) is not None
    time.sleep(0.05)
    n_evicted = store.sweep()
    assert n_evicted == 1
    assert store.get(sid) is None


def test_get_resets_idle_timer() -> None:
    """``get(sid)`` обновляет last_used_at — сессия не протухает от простого ожидания."""
    store = SessionStore(ttl_sec=0.05)
    sid = store.get_or_create(None).session_id
    # Частые get'ы — таймер сбрасывается, сессия должна пережить TTL.
    for _ in range(5):
        time.sleep(0.02)
        assert store.get(sid) is not None
    store.sweep()
    assert store.get(sid) is not None


def test_get_or_create_triggers_sweep() -> None:
    """``get_or_create`` сам вызывает sweep — TTL-срок соблюдается без явного вызова."""
    store = SessionStore(ttl_sec=0.01)
    # Создаём сессию, ждём больше TTL, затем создаём другую.
    store.get_or_create("stale-1")
    time.sleep(0.05)
    fresh = store.get_or_create("fresh")
    # Старая должна быть автоматически выметена.
    assert store.get("stale-1") is None
    assert store.get("fresh") is fresh


# --- LRU --------------------------------------------------------------------


def test_lru_evicts_oldest_but_never_default() -> None:
    """default-сессия не вытесняется, вытесняется самая старая из остальных."""
    store_limited = SessionStore(max_sessions=2)
    # 1/2: default.
    default_session = store_limited.get_or_create("default")
    # 2/2: явный id ``first`` — НЕ default.
    first = store_limited.get_or_create("first")
    assert first.session_id == "first"
    # 3-й вызов — лимит превышен, default защищён, "first" вытесняется.
    store_limited.get_or_create("third")
    assert store_limited.get("default") is default_session, "default не должен вытесняться"
    assert store_limited.get("first") is None, "first должен быть вытеснен"
    assert store_limited.get("third") is not None


def test_lru_protects_newly_created_session() -> None:
    """При создании сессия не должна вытеснить сама себя."""
    # С лимитом 3: default + s1 + s2 — все три живут.
    store = SessionStore(max_sessions=3)
    default_session = store.get_or_create("default")
    s1 = store.get_or_create("s1")
    s2 = store.get_or_create("s2")
    assert store.get("default") is default_session
    assert store.get("s1") is s1
    assert store.get("s2") is s2
    # 4-й вызов: default защищён, s1/s2 — кандидаты. Самая старая из них — s1.
    store.get_or_create("s3")
    assert store.get("default") is not None
    assert store.get("s1") is None, "s1 вытеснена как самая старая"
    assert store.get("s2") is s2, "s2 ещё свежая — не тронута"
    assert store.get("s3") is not None


def test_lru_eviction_clears_state() -> None:
    """Вытесненная сессия тоже чистит state — нет висящих DataFrame'ов."""
    store = SessionStore(max_sessions=1)
    s1 = store.get_or_create("s1")
    s1.state["blocks"] = "huge_df"
    # Создаём вторую — должна вытеснить s1.
    store.get_or_create("s2")
    assert s1.state == {}, "вытеснение не очистило state"


# --- close ------------------------------------------------------------------


def test_close_clears_state(store: SessionStore) -> None:
    """``close()`` чистит state — GeoDataFrame'ы освобождаются явно."""
    s = store.get_or_create("x")
    sentinel = object()
    s.state["blocks"] = sentinel
    assert store.close("x") is True
    assert s.state == {}, "close не очистил state"


def test_close_unknown_returns_false(store: SessionStore) -> None:
    """``close()`` для несуществующей сессии — False, не KeyError."""
    assert store.close("nonexistent") is False


def test_close_removes_from_store(store: SessionStore) -> None:
    """После close() get_or_create создаст новую сессию (не вернёт старую)."""
    s = store.get_or_create("x")
    store.close("x")
    new_s = store.get_or_create("x")
    assert new_s is not s


# --- info -------------------------------------------------------------------


def test_info_does_not_leak_values(store: SessionStore) -> None:
    """``info()`` отдаёт только имена ключей, не их содержимое."""
    store.get_or_create("x").state["blocks"] = "secret_payload"
    store.get_or_create("x").state["api_key"] = "sk-1234567890"
    payload = json.dumps(store.info("x"))
    assert "secret_payload" not in payload
    assert "sk-1234567890" not in payload
    # А имена ключей — должны быть.
    info = store.info("x")
    assert "blocks" in info["keys"]
    assert "api_key" in info["keys"]


def test_info_all_returns_summary(store: SessionStore) -> None:
    """``info()`` без аргумента — список всех сессий + ttl/max."""
    store.get_or_create("a")
    store.get_or_create("b")
    info = store.info()
    assert info["ttl_sec"] == 60.0
    assert info["max_sessions"] == 8
    assert info["n_sessions"] == 2
    ids = {s["session_id"] for s in info["sessions"]}
    assert ids == {"a", "b"}


def test_info_unknown_returns_exists_false(store: SessionStore) -> None:
    """``info("nope")`` не падает, а возвращает ``exists: False``."""
    info = store.info("nope")
    assert info["exists"] is False


# --- потокобезопасность ----------------------------------------------------


def test_thread_safety_under_concurrent_create() -> None:
    """20 потоков создают сессии — стор не рассыпается, лимит соблюдён."""
    store = SessionStore(max_sessions=15)
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(20)

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=2.0)
            session = store.get_or_create(f"s-{i}")
            results.append(session.session_id)
        except BaseException as exc:  # noqa: BLE001 — ловим всё для отчёта
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(worker, range(20)))

    assert not errors, f"исключения в потоках: {errors}"
    # 20 уникальных id → 20 разных сессий, но лимит 15, после вытеснения
    # должно остаться не больше 15.
    assert len(results) == 20
    # Все сессии либо созданы, либо вытеснены — должно быть не больше max.
    info = store.info()
    assert info["n_sessions"] <= 15


def test_thread_safety_under_concurrent_state_writes() -> None:
    """100 параллельных записей в одну сессию — все ключи на месте, ни одна не потеряна."""
    store = SessionStore()
    session = store.get_or_create("hot")
    n_writers = 100

    def writer(i: int) -> None:
        session.state[f"k-{i}"] = i

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(writer, range(n_writers)))

    assert len(session.state) == n_writers
    assert all(session.state[f"k-{i}"] == i for i in range(n_writers))


# --- конструктор ------------------------------------------------------------


def test_constructor_rejects_non_positive_ttl() -> None:
    """TTL <= 0 → ValueError (защита от случайного OOM-вечного кэша)."""
    with pytest.raises(ValueError, match="ttl_sec"):
        SessionStore(ttl_sec=0)


def test_constructor_rejects_non_positive_max() -> None:
    """max_sessions <= 0 → ValueError."""
    with pytest.raises(ValueError, match="max_sessions"):
        SessionStore(max_sessions=0)


# --- синглтон ---------------------------------------------------------------


def test_singleton_returns_same_instance() -> None:
    """``get_session_store()`` возвращает один и тот же объект."""
    reset_session_store()
    a = get_session_store()
    b = get_session_store()
    assert a is b


def test_singleton_reset_returns_new() -> None:
    """``reset_session_store()`` действительно создаёт новый инстанс."""
    reset_session_store()
    a = get_session_store()
    reset_session_store()
    b = get_session_store()
    assert a is not b


# --- dataclass Session ------------------------------------------------------


def test_session_default_meta_is_empty() -> None:
    """``Session.meta`` — пустой dict по умолчанию (для scenario_id/project_id в шаге 06)."""
    s = Session(session_id="x")
    assert s.meta == {}
    assert s.data_dir is None
    assert s.output_dir is None