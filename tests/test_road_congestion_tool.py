from __future__ import annotations

from pathlib import Path

import pandas as pd

from blocksnet_agent.tools.network import make_network_tools


def _tool(tmp_path: Path, state: dict | None = None):
    tools = make_network_tools(
        {"state": state if state is not None else {}, "data_dir": tmp_path, "output_dir": tmp_path}
    )
    return next(item for item in tools if item.name == "compute_road_congestion")


def test_road_congestion_tool_is_registered_with_branch_contract(tmp_path: Path) -> None:
    tool = _tool(tmp_path)

    assert "OD-матрицу" in tool.description
    assert "feat/road_congestion" in tool.description
    schema = tool.args_schema.model_json_schema()
    assert schema["properties"]["accessibility"]["default"] == 10.0
    assert schema["properties"]["max_trips"]["default"] == 50000


def test_road_congestion_reports_missing_branch_inputs(tmp_path: Path, monkeypatch) -> None:
    import blocksnet.analysis.network as network

    monkeypatch.setattr(network, "origin_destination_matrix", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(network, "road_congestion", lambda *args, **kwargs: None, raising=False)
    state = {
        "blocks": pd.DataFrame(
            {"population": [1], "land_use": ["RESIDENTIAL"], "site_area": [1.0], "count_shop": [1]},
            index=[1],
        )
    }
    result = _tool(tmp_path, state).invoke({})

    assert result.startswith("Ошибка:")
    assert "blocks_to_nodes" in result
    assert "blocks_to_nodes.pickle" in result


def test_road_congestion_stops_before_assignment_when_trip_budget_exceeded(
    tmp_path: Path, monkeypatch
) -> None:
    import networkx as nx
    import blocksnet.analysis.network as network
    import blocksnet.analysis.services as services

    state = {"blocks": pd.DataFrame({"population": [10], "land_use": ["RESIDENTIAL"], "site_area": [1.0], "count_shop": [1]}, index=[1])}
    blocks_to_nodes = pd.DataFrame([[1.0, 2.0]], index=[1], columns=[10, 11])
    nodes_to_nodes = pd.DataFrame([[0.0, 1.0], [1.0, 0.0]], index=[10, 11], columns=[10, 11])
    graph = nx.MultiDiGraph(crs=3857)
    graph.add_node(10, x=0.0, y=0.0)
    graph.add_node(11, x=1.0, y=0.0)
    graph.add_edge(10, 11, time_min=1.0, lanes=1)
    graph.add_edge(11, 10, time_min=1.0, lanes=1)

    monkeypatch.setattr(
        "blocksnet_agent.tools.network._load_road_congestion_inputs",
        lambda _: (blocks_to_nodes, nodes_to_nodes, graph),
    )
    monkeypatch.setattr(services, "services_count", lambda blocks: pd.DataFrame({"count": [1]}, index=blocks.index))
    monkeypatch.setattr(
        network,
        "origin_destination_matrix",
        lambda *args, **kwargs: pd.DataFrame([[0, 6], [5, 0]], index=[10, 11], columns=[10, 11]),
        raising=False,
    )
    called = {"assignment": False}

    def fake_assignment(*args, **kwargs):
        called["assignment"] = True
        return graph

    monkeypatch.setattr(network, "road_congestion", fake_assignment, raising=False)
    result = _tool(tmp_path, state).invoke({"max_trips": 10})

    assert "11 поездок > max_trips=10" in result
    assert called["assignment"] is False
    assert "origin_destination_matrix" not in state
