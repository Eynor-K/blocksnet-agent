from __future__ import annotations

from pathlib import Path

import pandas as pd

from blocksnet_agent.agent import _coherence_issues
from blocksnet_agent.tools.data import NO_DATA_MARKER, make_data_tools

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _data_tools(state):
    ctx = {"state": state, "data_dir": DATA_DIR, "output_dir": Path("/tmp")}
    return {tool.name: tool for tool in make_data_tools(ctx)}


def test_absent_metric_key_returns_stable_no_data_marker_with_available_keys():
    tools = _data_tools({"blocks": pd.DataFrame(index=[1]), "metric_x": pd.Series([1.0], index=[1])})

    result = tools["get_metric_for_block"].invoke({"result_key": "missing_metric", "block_id": 1})

    assert result.startswith(NO_DATA_MARKER)
    assert "result_key=missing_metric" in result
    assert "Доступные" in result


def test_absent_block_index_returns_stable_no_data_marker_not_zero():
    tools = _data_tools({"blocks": pd.DataFrame(index=[1]), "metric_x": pd.Series([0.5], index=[1])})

    result = tools["get_metric_for_block"].invoke({"result_key": "metric_x", "block_id": 2})

    assert result.startswith(NO_DATA_MARKER)
    assert "block_id=2" in result
    assert "do not interpret as zero" in result


def test_real_zero_metric_remains_numeric_zero():
    tools = _data_tools({"blocks": pd.DataFrame(index=[1]), "metric_x": pd.Series([0.0], index=[1])})

    result = tools["get_metric_for_block"].invoke({"result_key": "metric_x", "block_id": 1})

    assert not result.startswith(NO_DATA_MARKER)
    assert "0.0000" in result


def test_final_answer_consistency_rejects_fabricated_zero_for_no_data_pair():
    steps = [
        {
            "tool": "get_metric_for_block",
            "tool_input": "{'result_key': 'metric_x', 'block_id': 10}",
            "observation": f"{NO_DATA_MARKER}: block_id=10 absent in result_key=metric_x; do not interpret as zero",
        }
    ]
    output_text = "ANALYSIS PLAN: Проверить metric_x по кварталу.\nRESULT: Для block_id 10 metric_x = 0.00."

    issues = _coherence_issues(output_text, steps)

    assert any("NO_DATA" in issue and "metric_x" in issue and "10" in issue for issue in issues)
