from __future__ import annotations

from pathlib import Path

import pandas as pd

from blocksnet_agent.tools.optimize import make_optimize_tools

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _tool(state):
    ctx = {"state": state, "data_dir": DATA_DIR, "output_dir": Path("/tmp")}
    return make_optimize_tools(ctx)[0]


def _blocks():
    return pd.DataFrame(
        {
            "population": [0, 50, 200, 0, 100],
            "living_area": [0, 10, 20, 0, 5],
            "capacity_school": [0, 0, 0, 0, 0],
        },
        index=[10, 11, 12, 13, 14],
    )


def test_low_provision_requires_cached_service_provision_and_ignores_accessibility_fallback():
    state = {
        "blocks": _blocks(),
        "mean_accessibility": pd.Series([1, 2, 3, 4, 5], index=[10, 11, 12, 13, 14]),
    }

    result = _tool(state).invoke({"criterion": "low_provision", "service_type": "school", "count": 3})

    assert "сначала вызови compute_service_provision('school')" in result
    assert "Кандидаты" not in result
    assert "mean_accessibility" not in result


def test_low_provision_excludes_zero_demand_and_ranks_positive_demand_deficits():
    state = {
        "blocks": _blocks(),
        "competitive_provision_school": pd.DataFrame(
            {"provision": [0.0, 0.2, 0.0, 0.0, 0.8]},
            index=[10, 11, 12, 13, 14],
        ),
    }

    result = _tool(state).invoke({"criterion": "low_provision", "service_type": "school", "count": 3})

    assert "Кандидаты" in result
    assert "block_id 12" in result
    assert "block_id 11" in result
    assert "block_id 14" in result
    assert "block_id 10" not in result
    assert "block_id 13" not in result
    assert "исключено без применимого спроса: 2" in result
    assert "rank_reason" in result
