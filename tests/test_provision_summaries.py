from __future__ import annotations

from pathlib import Path

import pandas as pd

from blocksnet.enums import LandUse

from blocksnet_agent.tools.data import make_data_tools, resolve_service_name
from blocksnet_agent.tools.optimize import UnknownServiceSet, _available_service_weights
from blocksnet_agent.tools.provision import _format_distribution_summary

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_category_like_service_query_does_not_auto_resolve_to_unrelated_single_service():
    canon, ranked = resolve_service_name("healthcare", DATA_DIR, ["school", "polyclinic", "pharmacy"])

    assert canon is None
    assert ranked


def test_ambiguous_service_query_returns_none_with_candidates(tmp_path):
    data_dir = tmp_path
    (data_dir / "service_type.json").write_text(
        '[{"name":"alpha_clinic","name_ru":"shared label"}, {"name":"beta_clinic","name_ru":"shared label"}]',
        encoding="utf-8",
    )

    canon, ranked = resolve_service_name("shared label", data_dir, ["alpha_clinic", "beta_clinic"])

    assert canon is None
    assert {name for name, _score in ranked[:2]} == {"alpha_clinic", "beta_clinic"}


def test_unknown_service_set_error_lists_candidates_without_imperative_single_retry():
    blocks = pd.DataFrame({"population": [1], "capacity_school": [0], "capacity_polyclinic": [0]})

    try:
        _available_service_weights("healthcare", blocks, LandUse.RESIDENTIAL, DATA_DIR)
    except UnknownServiceSet as exc:
        message = exc.message
    else:  # pragma: no cover
        raise AssertionError("expected UnknownServiceSet")

    assert "Top candidates" in message or "кандидат" in message
    assert "Повтори вызов" not in message
    assert "Ближайшее валидное имя" not in message


def test_get_analysis_results_for_provision_shows_distribution_and_top_deficit_rows():
    state = {
        "blocks": pd.DataFrame({"population": [0, 50, 100]}, index=[1, 2, 3]),
        "competitive_provision_school": pd.DataFrame({"provision": [0.0, 0.0, 0.7]}, index=[1, 2, 3]),
    }
    tools = {tool.name: tool for tool in make_data_tools({"state": state, "data_dir": DATA_DIR, "output_dir": Path("/tmp")})}

    result = tools["get_analysis_results"].invoke({"result_key": "competitive_provision_school"})

    assert "Распределение" in result
    assert "top deficit" in result.lower() or "дефицит" in result.lower()
    assert "block_id 2" in result
    assert "block_id 1" not in result


def test_distribution_summary_includes_zero_share_and_positive_demand_deficit_examples():
    blocks = pd.DataFrame({"population": [0, 50, 100]}, index=[1, 2, 3])
    provision = pd.DataFrame({"provision": [0.0, 0.0, 0.7]}, index=[1, 2, 3])

    summary = _format_distribution_summary(provision, blocks, top_n=5)

    assert "доля кварталов без обеспеченности" in summary
    assert "top deficit" in summary.lower() or "дефицит" in summary.lower()
    assert "block_id 2" in summary
    assert "block_id 1" not in summary
