"""P1.3: регресс-тесты на починку PTR-контура гипотез.

Что чиним:
1. ``numbers[-1]`` в ``_classify_numeric_prediction`` — брал последнее число
   из evidence (длинная таблица → «хвост» колонки). Теперь — адресный путь
   через ``state[result_key]``, fallback только по строке с нужным ``block_id``.
2. ``block_id=42 < median`` — оператор ``<`` не должен захватывать ``42``
   как порог.
3. ``_test_was_called`` — substring-матч давал ложные срабатывания на
   похожих именах tool'ов. Теперь — точное равенство.
"""
from __future__ import annotations

import pandas as pd
import pytest

from blocksnet_agent.hypotheses import (
    _classify_numeric_prediction,
    _extract_threshold_operator,
    _observed_value_for_block,
    _test_was_called,
    Hypothesis,
    HypothesisLedger,
    classify_hypothesis_ledger,
)


# ---- 1. ``numbers[-1]`` больше не используется ---------------------------------


def test_classify_does_not_use_last_number_from_long_table() -> None:
    """P1.3: длинный табличный evidence (как в schools-15:58) НЕ даёт
    ``0.130794 >= 3 → refuted``. prediction ``provision >= 0.3`` с evidence,
    где упоминания нужного block_id НЕТ, должно стать inconclusive
    (а не refuted по хвостовому ``0.130794``).
    """
    # ``block_id 999`` отсутствует в evidence (там 0..99), но prediction
    # требует ``block_id 999 >= 0.3``. Должно быть inconclusive.
    prediction = "competitive_provision_school block_id 999 >= 0.3"
    long_table_evidence = "\n".join(
        f"compute_service_provision: block_id {i} value: 0.{i:07d} other: 0.130794"
        for i in range(100)
    )
    result = _classify_numeric_prediction(prediction, long_table_evidence, state={})
    assert result is not None
    assert result[0] == "inconclusive", (
        f"длинная таблица не должна подменять evidence хвостовым числом; got {result}"
    )


def test_classify_uses_state_address_path() -> None:
    """P1.3: если state содержит result_key с метрикой для block_id —
    используем её напрямую, не из evidence.
    """
    state = {
        "competitive_provision_school": pd.DataFrame(
            {"provision": [0.5, 0.2, 0.9]},
            index=[10, 11, 12],
        ),
    }
    # block_id=11 имеет provision=0.2; prediction требует >= 0.5 — refuted.
    prediction = "competitive_provision_school block_id 11 >= 0.5"
    result = _classify_numeric_prediction(prediction, "", state=state)
    assert result is not None
    assert result[0] == "refuted"
    # evidence: ссылается на state, не на прозу.
    assert "from state" in result[1]


# ---- 2. ``block_id=42 < median`` — оператор НЕ ловит ``42`` --------------------


def test_extract_threshold_ignores_block_id_followed_by_operator() -> None:
    """P1.3: ``block_id 42 < median`` — оператор ``<`` НЕ должен попасть
    в threshold.
    """
    # prediction без настоящего threshold — None.
    pred = "block_id 42 < median"
    assert _extract_threshold_operator(pred) is None


def test_extract_threshold_works_when_block_id_not_adjacent() -> None:
    pred = "block_id 42 provision_strong > 0.3"
    op, threshold = _extract_threshold_operator(pred)
    assert op == ">"
    assert threshold == pytest.approx(0.3)


def test_extract_threshold_keeps_block_id_value_when_no_operator() -> None:
    """P1.3: ``=`` в ``block_id=42`` — это НЕ порог. Должен искаться дальше."""
    pred = "block_id=42 median of 0.3, expected 0.5"
    # Здесь нет оператора, который бы не был частью ``block_id=42``,
    # поэтому вернётся None (нет threshold).
    assert _extract_threshold_operator(pred) is None


# ---- 3. ``_test_was_called`` — точное равенство ------------------------------


def test_test_was_called_requires_exact_match() -> None:
    """P1.3: ``compute_service_provision`` НЕ матчит ``service_provision``."""
    steps = [
        {"tool": "compute_service_provision", "observation": "..."},
        {"tool": "compute_scenario_provision", "observation": "..."},
    ]
    assert _test_was_called("compute_service_provision", steps) is True
    # Точное имя tool'а — должно сработать.
    assert _test_was_called("compute_scenario_provision", steps) is True
    # Подстрока — НЕ должна сработать (substring убран в P1.3).
    assert _test_was_called("service_provision", steps) is False


def test_test_was_called_handles_empty_inputs() -> None:
    assert _test_was_called("", steps=[]) is False
    assert _test_was_called("anything", steps=[]) is False
    assert _test_was_called("anything", steps=[{"tool": "", "observation": ""}]) is False


# ---- 4. integration: classify через полный леджер -----------------------------


def test_classify_ledger_uses_state_for_numeric_pred() -> None:
    """P1.3: ledger с prediction по адресу из state — supported/refuted корректно."""
    state = {
        "competitive_provision_school": pd.DataFrame(
            {"provision": [0.8, 0.2]},
            index=[100, 200],
        ),
    }
    ledger = HypothesisLedger(
        hypotheses=[
            Hypothesis(
                id="H1",
                claim="block 200 имеет дефицит",
                prediction="competitive_provision_school block_id 200 < 0.3",
                test="compute_service_provision",
            ),
        ]
    )
    steps = [
        {"tool": "compute_service_provision", "observation": "school provision computed"},
    ]
    out = classify_hypothesis_ledger(ledger, steps, lambda prompt: None, state)
    h = out.hypotheses[0]
    assert h.status == "supported", f"state says 0.2 < 0.3 → supported; got {h.status}"


def test_classify_ledger_returns_inconclusive_when_no_block_in_evidence() -> None:
    """P1.3: если evidence не содержит block_id из prediction, а в state
    тоже нет — inconclusive, НЕ refuted по хвостовому числу evidence.
    """
    state = {}  # пустой state
    ledger = HypothesisLedger(
        hypotheses=[
            Hypothesis(
                id="H1",
                claim="block 999 дефицитен",
                prediction="competitive_provision_school block_id 999 < 0.3",
                test="compute_service_provision",
            ),
        ]
    )
    # В evidence — другая таблица, про block_id 0..100, в т.ч. хвост 0.130794.
    evidence_lines = "\n".join(
        f"compute_service_provision: block_id {i} value: {0.5 + i * 0.001:.7f}"
        for i in range(50)
    )
    steps = [
        {"tool": "compute_service_provision", "observation": evidence_lines},
    ]
    out = classify_hypothesis_ledger(ledger, steps, lambda prompt: None, state)
    h = out.hypotheses[0]
    # block_id 999 в evidence нет → state пуст → inconclusive (не refuted по хвосту).
    assert h.status == "inconclusive", f"got {h.status}: {h.evidence}"


# ---- 5. observed_value_for_block ---------------------------------------------


def test_observed_value_for_block_picks_first_positive_in_line() -> None:
    """P1.3: первое положительное число в строке, относящейся к block_id."""
    evidence = (
        "compute_service_provision: block_id 42 provision_strong=0.5 missing=10\n"
        "compute_service_provision: block_id 43 provision_strong=0.7 missing=12\n"
    )
    assert _observed_value_for_block(evidence, 42) == 0.5
    assert _observed_value_for_block(evidence, 43) == 0.7
    assert _observed_value_for_block(evidence, 999) is None


def test_observed_value_handles_compact_block_id_equals() -> None:
    evidence = "compute_service_provision: block_id=42 provision=0.8"
    assert _observed_value_for_block(evidence, 42) == 0.8
