"""P1.6: регресс-тесты на накладывающиеся слои (CSP + weighted overlay)."""
from __future__ import annotations

import pandas as pd

from blocksnet_agent.hypotheses import (
    Hypothesis,
    HypothesisLedger,
    overlay_candidates,
)


def _blocks() -> pd.DataFrame:
    # 5 блоков с разным provision. provision=0 → дефицит.
    return pd.DataFrame(
        {
            "population": [100, 200, 300, 400, 500],
            "capacity_school": [1, 1, 1, 1, 1],
        },
        index=[10, 11, 12, 13, 14],
    )


def test_ledger_layers_filters_by_result_key() -> None:
    ledger = HypothesisLedger(
        hypotheses=[
            Hypothesis(id="H1", claim="school deficit", prediction="p<0.5", test="prov"),
            # P1.6: «нарративная» гипотеза (без result_key) не становится слоем.
            Hypothesis(id="H2", claim="narrative", prediction="x", test="t"),
            # P1.6: «слой» — гипотеза с result_key.
            Hypothesis(id="H3", claim="layer", prediction="y", test="t", result_key="competitive_provision_school"),
        ]
    )
    assert len(ledger.hypotheses) == 3
    layers = ledger.layers()
    assert [item.id for item in layers] == ["H3"]
    assert not ledger.hard_layers()  # по умолчанию kind=soft
    assert [item.id for item in ledger.soft_layers()] == ["H3"]


def test_overlay_candidates_returns_empty_when_no_layers() -> None:
    ledger = HypothesisLedger(hypotheses=[Hypothesis(id="H1", claim="x", prediction="y", test="z")])
    result = overlay_candidates(ledger, state={})
    assert result["candidates"] == []
    assert result["hard_passed"] == 0
    assert result["hard_total"] == 0


def test_overlay_candidates_applies_hard_layer_as_mask() -> None:
    """P1.6: hard-слой с direction=mask отрезает блоки с population == 0
    (CSP — отсечение домена). Когда у нас всех >0, hard не отсекает ничего и
    остаётся только soft-скрининг по дефициту provision.
    """
    state = {
        "blocks": _blocks(),
        "competitive_provision_school": pd.DataFrame(
            {
                "population": [100, 200, 300, 400, 500],
                "provision_strong": [0.1, 0.5, 0.2, 0.8, 0.3],
            },
            index=[10, 11, 12, 13, 14],
        ),
    }
    ledger = HypothesisLedger(
        hypotheses=[
            # hard-mask: отрезает тех, у кого population == 0. У нас таких нет —
            # слой «недиагностичный».
            Hypothesis(
                id="hard_mask",
                claim="only_blocks_with_population",
                prediction=">0",
                test="t",
                result_key="competitive_provision_school",
                column="population",
                kind="hard",
                weight=1.0,
                direction="mask",
            ),
            # soft: ищем кварталы с дефицитом provision.
            Hypothesis(
                id="soft_deficit",
                claim="deficit",
                prediction="<median",
                test="t",
                result_key="competitive_provision_school",
                column="provision_strong",
                kind="soft",
                weight=1.0,
                direction="below",
            ),
        ]
    )
    result = overlay_candidates(ledger, state, top_n=5)
    # hard_total=1, hard-mask никого не отрезал → nondiagnostic_layers=1.
    # Soft-вклад: 1 - v: 10 (0.9), 12 (0.8), 14 (0.7), 11 (0.5), 13 (0.2).
    assert result["hard_total"] == 1
    assert result["nondiagnostic_layers"] == 1
    assert [item["block_id"] for item in result["candidates"]] == [10, 12, 14, 11, 13]


def test_overlay_candidates_weighted_overlay_ranks_correctly() -> None:
    """P1.6: с одним soft-слоем ``below`` кандидаты должны быть упорядочены
    по убыванию score = w * (1 - v), где v — provision. Чем ниже provision, тем выше score.
    """
    state = {
        "blocks": _blocks(),
        "competitive_provision_school": pd.DataFrame(
            {"provision_strong": [0.1, 0.5, 0.2, 0.8, 0.3]},
            index=[10, 11, 12, 13, 14],
        ),
    }
    ledger = HypothesisLedger(
        hypotheses=[
            Hypothesis(
                id="soft_deficit",
                claim="deficit",
                prediction="provision<median",
                test="t",
                result_key="competitive_provision_school",
                column="provision_strong",
                kind="soft",
                weight=1.0,
                direction="below",
            ),
        ]
    )
    result = overlay_candidates(ledger, state, top_n=5)
    # Soft-слой не отсекает, только вносит вклад. Медиана provision = 0.3.
    # Score = 1 - v, поэтому: 10 (0.9), 12 (0.8), 14 (0.7), 11/13 (0.5).
    block_ids = [item["block_id"] for item in result["candidates"]]
    assert block_ids == [10, 12, 14, 11, 13]
    # Самый дефицитный (10) — с наивысшим score; монотонно убывающий.
    scores = [item["score"] for item in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_overlay_candidates_uses_normalized_weights() -> None:
    """P1.6: Σwᵢ нормируется на единицу. Проверяем, что при w_a=3, w_b=1
    итоговый score = (0.75 * 1.0) + (0.25 * 1.0) = 1.0, а НЕ 4.0.
    """
    state = {
        "blocks": _blocks(),
        "layer_a": pd.DataFrame({"v": [0.0, 0.5, 0.4, 0.5, 0.4]}, index=[10, 11, 12, 13, 14]),
        "layer_b": pd.DataFrame({"v": [0.0, 0.4, 0.5, 0.4, 0.5]}, index=[10, 11, 12, 13, 14]),
    }
    ledger = HypothesisLedger(
        hypotheses=[
            Hypothesis(
                id="A",
                claim="a",
                prediction="a<median",
                test="t",
                result_key="layer_a",
                column="v",
                kind="soft",
                weight=3.0,
                direction="below",
            ),
            Hypothesis(
                id="B",
                claim="b",
                prediction="b<median",
                test="t",
                result_key="layer_b",
                column="v",
                kind="soft",
                weight=1.0,
                direction="below",
            ),
        ]
    )
    result = overlay_candidates(ledger, state, top_n=5)
    # Soft-вклады: layer_a (w=3), layer_b (w=1) → norm 0.75/0.25.
    # v=0 → score=1.0 для каждой. Для 10 (0.0, 0.0) — суммарный score = 0.75+0.25 = 1.0.
    # Остальные — меньше, но в кандидатах тоже. top_n=5 — все 5 блоков.
    block_ids = [item["block_id"] for item in result["candidates"]]
    assert block_ids[0] == 10
    assert abs(result["candidates"][0]["score"] - 1.0) < 1e-6
