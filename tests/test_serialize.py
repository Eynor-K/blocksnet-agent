from __future__ import annotations

import json
from pathlib import Path

import pytest

from blocksnet_mcp.serialize import to_json


def test_to_json_extracts_contract_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260618-120000-abcdef"
    run_dir.mkdir()
    artifact = run_dir / "scenario.csv"
    artifact.write_text("block_id,value\n1,2\n", encoding="utf-8")
    (run_dir / "run_log.json").write_text(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "tool": "compute_scenario_provision",
                        "observation": "pitch strong_before: 0.7 strong_after: 0.8 missing_before: 10 missing_after: 5",
                    }
                ],
                "saved_files": [{"path": str(artifact), "kind": "csv"}],
            }
        ),
        encoding="utf-8",
    )

    # P1.1: задаём ``submitted_answer`` — это идиоматический путь. Структурный
    # payload приоритетнее regex-fallback.
    payload = to_json(
        {
            "input": "Где разместить спортивные площадки?",
            "output": "",
            "confidence": 0.78,  # P1.2: авторитетная формула (после fix)
            "limitations": ["local data only"],
            "run_dir": str(run_dir),
            "sections": {
                "ANALYSIS PLAN": "plan",
                "RESULT": "recommend block_id 12",
                "HYPOTHESES": (
                    "- id: H1; claim: Спорт дефицитен; prediction: pitch below median; "
                    "test: compute_service_provision; status: supported; evidence: observed"
                ),
            },
            "submitted_answer": {
                "question": "Где разместить спортивные площадки?",
                "result": "recommend block_id 12",
                "analysis_plan": "plan",
                "recommendations": [{"block_id": 12, "service_type": "pitch", "added_capacity": 1.0, "rationale": "deficit"}],
                "measured_effects": [{"service_type": "pitch", "strong_before": 0.7, "strong_after": 0.8, "missing_before": 10, "missing_after": 5, "source": "compute_scenario_provision"}],
                "confidence": 0.55,  # P1.2: самооценка агента (ниже, чем авторитетная)
                "limitations": ["local data only"],
                "salvaged": False,
            },
            "confidence_basis": [
                "data_basis=1.00*0.30=+0.30",
                "reflection=1.00*0.10=+0.10",
                "hypothesis_overlap=1.00*0.20=+0.20",
                "tool_diversity=1.00*0.10=+0.10",
                "scarcity=0.80*0.10=+0.08",
            ],
        }
    )

    assert payload["question"] == "Где разместить спортивные площадки?"
    assert payload["analysis_plan"] == "plan"
    # P1.2 fix: ``confidence`` теперь — авторитетная P1.2-формула (0.78),
    # а самооценка агента (0.55) лежит в ``confidence_self``.
    assert payload["confidence"] == 0.78
    assert payload["confidence_self"] == 0.55
    assert payload["confidence_basis"] == [
        "data_basis=1.00*0.30=+0.30",
        "reflection=1.00*0.10=+0.10",
        "hypothesis_overlap=1.00*0.20=+0.20",
        "tool_diversity=1.00*0.10=+0.10",
        "scarcity=0.80*0.10=+0.08",
    ]
    assert payload["limitations"] == ["local data only"]
    assert payload["recommendation_blocks"] == [12]  # P1.1: backward-compat поле
    assert payload["run_id"] == "20260618-120000-abcdef"
    assert payload["artifacts"] == ["scenario.csv"]
    assert payload["salvaged"] is False
    assert payload["measured_effects"][0]["service_type"] == "pitch"
    assert payload["recommendations"][0]["block_id"] == 12


def test_to_json_handles_empty_result() -> None:
    payload = to_json({})

    # P1.1: пустой результат → salvaged=True с маркером SALVAGED_ANSWER.
    assert payload["question"] == ""
    assert payload["analysis_plan"] == ""
    assert payload["result"] == ""
    assert payload["hypotheses"] == []
    assert payload["measured"] == {}
    assert payload["recommendation_blocks"] == []
    assert payload["confidence"] == 0.0
    assert payload["limitations"] == ["SALVAGED_ANSWER"]
    assert payload["artifacts"] == []
    assert payload["run_id"] == ""
    assert payload["salvaged"] is True


def test_to_json_wraps_string_limitations_and_deduplicates_blocks() -> None:
    payload = to_json(
        {
            "input": "test",
            "output": "",
            "limitations": "single limitation",
            "sections": {
                "RESULT": "recommend block_id 12, квартал 12 and block 7",
            },
        }
    )

    # P1.1: fallback (regex-парсинг) → salvaged=True, SALVAGED_ANSWER добавляется.
    assert "single limitation" in payload["limitations"]
    assert "SALVAGED_ANSWER" in payload["limitations"]
    assert payload["salvaged"] is True
    assert payload["recommendation_blocks"] == [12, 7]


def test_to_json_extracts_arrow_measured_from_run_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260618-130000-fedcba"
    run_dir.mkdir()
    (run_dir / "run_log.json").write_text(
        json.dumps(
            {
                "tool_calls": [
                    {
                        "tool": "compute_scenario_provision",
                        "observation": "scenario provision before→after: 0.45 → 0.62",
                    }
                ],
                "saved_files": [],
            }
        ),
        encoding="utf-8",
    )

    payload = to_json({"run_dir": str(run_dir)})

    assert payload["measured"]["scenario"]["strong_before"] == 0.45
    assert payload["measured"]["scenario"]["strong_after"] == 0.62
    assert payload["salvaged"] is True


def test_to_json_extracts_real_agent_summary_format() -> None:
    payload = to_json(
        {
            "sections": {
                "RESULT": (
                    "- Кварталы с наименьшей доступностью спортивных услуг: "
                    "[2, 4, 5, 11, 12, 14, 15, 26, 27, 36].\n"
                    "- Улучшение обеспеченности после добавления площадок: "
                    "convenience strong 0.359→0.380, missing 790→783; "
                    "kindergarten strong 0.938→0.938, missing 669→668."
                )
            }
        }
    )

    # P1.1: regex-fallback — recommendation_blocks всё ещё извлекаются.
    assert payload["recommendation_blocks"] == [2, 4, 5, 11, 12, 14, 15, 26, 27, 36]
    assert payload["measured"]["convenience"] == {
        "strong_before": 0.359,
        "strong_after": 0.38,
        "missing_before": 790.0,
        "missing_after": 783.0,
    }
    assert payload["measured"]["kindergarten"]["missing_after"] == 668.0
    assert payload["salvaged"] is True


def test_to_json_prefers_submitted_answer_over_regex(tmp_path: Path) -> None:
    """P1.1: ``submitted_answer`` имеет приоритет — regex-fallback не используется."""
    run_dir = tmp_path / "run_20260701-120000-aabbcc"
    run_dir.mkdir()
    (run_dir / "run_log.json").write_text(
        json.dumps({"tool_calls": [], "saved_files": []}),
        encoding="utf-8",
    )

    payload = to_json(
        {
            "input": "q",
            "run_dir": str(run_dir),
            "sections": {
                # В прозе есть block_id, который regex бы подобрал; но ``submitted_answer``
                # задаёт другой набор — он и побеждает.
                "RESULT": "recommend block_id 99",
            },
            "submitted_answer": {
                "question": "q",
                "result": "structured answer",
                "recommendations": [{"block_id": 42, "service_type": "school", "added_capacity": None, "rationale": "test"}],
                "measured_effects": [],
                "confidence": 0.55,
                "limitations": [],
                "salvaged": False,
            },
        }
    )

    assert payload["recommendation_blocks"] == [42]  # из submitted_answer, не из regex
    assert payload["salvaged"] is False
    assert "SALVAGED_ANSWER" not in payload["limitations"]


def test_to_json_filters_invalid_block_ids_in_salvage_path(tmp_path: Path) -> None:
    """P0.5: regex-вытащенные block_id фильтруются против индекса кварталов города.

    Без валидации регэксп вытащил бы [99, 10001, 6521] из текста REFLECTION;
    с valid_block_ids=[42, 99] — останется только [99].
    """
    from blocksnet_mcp.serialize import _filter_valid_block_ids

    assert _filter_valid_block_ids([99, 10001, 6521], {42, 99}) == [99]
    assert _filter_valid_block_ids([99, 10001], None) == [99, 10001]  # None → без фильтра

    run_dir = tmp_path / "run_20260709-120000-valid01"
    run_dir.mkdir()
    (run_dir / "run_log.json").write_text(
        json.dumps({"tool_calls": [], "saved_files": []}),
        encoding="utf-8",
    )

    payload = to_json(
        {
            "input": "q",
            "run_dir": str(run_dir),
            "sections": {
                "REFLECTION": "Лидеры по дефициту: block_id 99, 10001, 6521 — последний транспортный.",
            },
            "valid_block_ids": [42, 99, 100, 101],  # 10001 и 6521 — нереальные
        }
    )

    assert payload["recommendation_blocks"] == [99]
    assert payload["salvaged"] is True
