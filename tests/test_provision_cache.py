"""P0.1: регресс-тесты на provision-кэш и LP-бюджет.

Гарантируем: (а) cache-hit по контенту входа (population+capacity), а не по строковому
ключу; (б) LP-бюджет ``_LP_BUDGET`` отсекает «свип по нецелевым сервисам»; (в) для
``compute_scenario_provision`` before считается через общий state, а after
кэшируется отдельно по своему fingerprint.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from blocksnet_agent.tools.provision import (
    _LP_BUDGET,
    _compute_single_service_provision,
    _content_hash,
    _lp_budget_exceeded,
    _register_lp,
    _service_df,
    _service_df_fingerprint,
)
from blocksnet_agent.tools.optimize import _service_df_from_blocks


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _blocks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "population": [100, 200, 300],
            "capacity_school": [1, 2, 3],
        },
        index=[10, 11, 12],
    )


def test_content_hash_is_stable_for_same_input() -> None:
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    h1 = _content_hash(df)
    h2 = _content_hash(df.copy())
    assert h1 == h2
    assert len(h1) == 16


def test_content_hash_changes_when_data_changes() -> None:
    df_a = pd.DataFrame({"a": [1, 2]})
    df_b = pd.DataFrame({"a": [1, 99]})
    assert _content_hash(df_a) != _content_hash(df_b)


def test_service_df_fingerprint_reflects_capacity_changes() -> None:
    """P0.1: fingerprint отражает изменения capacity, а не только population."""
    blocks_a = pd.DataFrame(
        {"population": [100, 200], "capacity_school": [1, 2]},
        index=[10, 11],
    )
    blocks_b = blocks_a.copy()
    blocks_b.loc[10, "capacity_school"] = 50

    # Используем только нужные колонки, чтобы fingerprint не зависел от других
    # атрибутов DataFrame (geometry, site_area и т.п.) и не требовал acc_mx.
    df_a = blocks_a[["population", "capacity_school"]].rename(columns={"capacity_school": "capacity"})
    df_b = blocks_b[["population", "capacity_school"]].rename(columns={"capacity_school": "capacity"})

    fp_a = _service_df_fingerprint(df_a)
    fp_b = _service_df_fingerprint(df_b)

    assert fp_a != fp_b, "fingerprint должен меняться при изменении capacity"


def test_lp_budget_tracks_real_calls() -> None:
    state: dict = {}
    assert not _lp_budget_exceeded(state)
    for _ in range(_LP_BUDGET):
        _register_lp(state)
    assert _lp_budget_exceeded(state)


def test_compute_single_service_provision_caches_by_fingerprint(tmp_path: Path, monkeypatch) -> None:
    """P0.1: повторный вызов с теми же кварталами — cache-hit без LP-счётчика."""
    state: dict = {}
    blocks = _blocks()
    acc_mx = pd.DataFrame([[0, 1, 1], [1, 0, 1], [1, 1, 0]], dtype="float64")
    state["blocks"] = blocks
    state["acc_mx"] = acc_mx

    # Заглушки ``competitive_provision`` + ``provision_strong_total`` через monkeypatch —
    # проверяем только cache-hit, не работу LP.
    import blocksnet_agent.tools.provision as provision_module

    call_count = {"n": 0}

    def fake_competitive_provision(blocks_df, accessibility_matrix, accessibility, demand=None, max_depth=1, self_supply=True):
        call_count["n"] += 1
        blocks_df = blocks_df.copy()
        blocks_df["demand_within"] = 0.0
        blocks_df["demand_without"] = 0.0
        blocks_df["demand_left"] = blocks_df["capacity"]
        blocks_df["capacity_left"] = blocks_df["capacity"]
        blocks_df["provision_strong"] = 0.0
        blocks_df["provision_weak"] = 0.0
        return blocks_df, pd.DataFrame()

    monkeypatch.setattr(provision_module, "competitive_provision", fake_competitive_provision)
    monkeypatch.setattr(provision_module, "provision_strong_total", lambda df: 0.0)
    monkeypatch.setattr(provision_module, "provision_weak_total", lambda df: 0.0)

    s1 = _compute_single_service_provision(state, DATA_DIR, tmp_path, "school", 15, 1)
    s2 = _compute_single_service_provision(state, DATA_DIR, tmp_path, "school", 15, 1)

    assert call_count["n"] == 1, f"второй вызов должен быть cache-hit, было {call_count['n']} LP"
    assert s1 == s2
    assert state["_lp_count"] == 1


def test_compute_single_service_provision_lp_budget_returns_partial(tmp_path: Path, monkeypatch) -> None:
    """P0.1: исчерпание LP-бюджета → ``lp_skipped=True`` и ноль новых LP."""
    state: dict = {}
    state["acc_mx"] = pd.DataFrame([[0, 1, 1], [1, 0, 1], [1, 1, 0]], dtype="float64")

    import blocksnet_agent.tools.provision as provision_module

    call_count = {"n": 0}

    def fake_competitive_provision(blocks_df, accessibility_matrix, accessibility, demand=None, max_depth=1, self_supply=True):
        call_count["n"] += 1
        blocks_df = blocks_df.copy()
        blocks_df["demand_within"] = 0.0
        blocks_df["demand_without"] = 0.0
        blocks_df["demand_left"] = blocks_df["capacity"]
        blocks_df["capacity_left"] = blocks_df["capacity"]
        blocks_df["provision_strong"] = 0.0
        blocks_df["provision_weak"] = 0.0
        return blocks_df, pd.DataFrame()

    monkeypatch.setattr(provision_module, "competitive_provision", fake_competitive_provision)
    monkeypatch.setattr(provision_module, "provision_strong_total", lambda df: 0.0)
    monkeypatch.setattr(provision_module, "provision_weak_total", lambda df: 0.0)

    # На каждой итерации меняем capacity, чтобы fingerprint менялся и cache-hit не
    # срабатывал. После ``_LP_BUDGET`` успешных LP следующий вызов должен вернуть
    # ``lp_skipped=True`` и НЕ делать новый LP.
    for i in range(_LP_BUDGET + 1):
        blocks = pd.DataFrame(
            {
                "population": [100, 200, 300],
                "capacity_school": [1 + i, 2 + i, 3 + i],  # ← уникальный fingerprint
            },
            index=[10, 11, 12],
        )
        state["blocks"] = blocks
        s = _compute_single_service_provision(state, DATA_DIR, tmp_path, "school", 15, 1)
        if i < _LP_BUDGET:
            assert s.get("lp_skipped") is not True, f"call {i} shouldn't be skipped"
        else:
            assert s.get("lp_skipped") is True, f"call {i} must be skipped (LP budget exhausted)"
            assert math.isnan(s["strong"])

    assert call_count["n"] == _LP_BUDGET, (
        f"после исчерпания бюджета новых LP быть не должно; было {call_count['n']}"
    )


def test_service_df_from_blocks_builds_capacity_from_modified_blocks() -> None:
    blocks = _blocks()
    blocks_changed = blocks.copy()
    blocks_changed.loc[10, "capacity_school"] = 99
    df = _service_df_from_blocks(blocks_changed, "school")
    assert int(df.loc[10, "capacity"]) == 99
    assert int(df.loc[10, "population"]) == 100
