from __future__ import annotations

import math
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from blocksnet_agent.tools.network import (
    _OD_SCAN_CHUNK_ROWS,
    _road_congestion_summary,
    _save_sparse_od,
    make_network_tools,
)


def _tool(tmp_path: Path, state: dict | None = None):
    tools = make_network_tools(
        {"state": state if state is not None else {}, "data_dir": tmp_path, "output_dir": tmp_path}
    )
    return next(item for item in tools if item.name == "compute_road_congestion")


def _make_inputs(tmp_path: Path):
    """Build a toy but fully valid OD+graph dataset.

    2 blocks × 3 nodes. Blocks have population, land_use, site_area and a
    ``count_shop`` column that ``services_count`` understands. Graph is a
    directed multigraph with int EPSG, x/y nodes, time_min and lanes edges.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    geom_a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    geom_b = Polygon([(2, 0), (3, 0), (3, 1), (2, 1)])
    blocks = gpd.GeoDataFrame(
        {
            "population": [500, 300],
            "land_use": ["RESIDENTIAL", "BUSINESS"],
            "site_area": [100_000.0, 80_000.0],
            "count_shop": [3, 5],
            "geometry": [geom_a, geom_b],
        },
        index=pd.Index([101, 102], name="block_id"),
        crs="EPSG:3857",
    )
    # ``pd.DataFrame({...Series...})`` upcasts integer Series to float64 if
    # other columns are float; restore int64 for ``BlocksSchema`` compatibility.
    blocks["population"] = blocks["population"].astype("int64")
    blocks["count_shop"] = blocks["count_shop"].astype("int64")

    blocks_to_nodes = pd.DataFrame(
        [[2.0, 3.0, 4.0], [5.0, 2.5, 3.5]],
        index=pd.Index([101, 102], name="block_id"),
        columns=pd.Index([10, 11, 12], name="node_id"),
        dtype="float32",
    )
    nodes_to_nodes = pd.DataFrame(
        [
            [0.0, 1.0, 1.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
        ],
        index=pd.Index([10, 11, 12], name="node_id"),
        columns=pd.Index([10, 11, 12], name="node_id"),
        dtype="float32",
    )

    graph = nx.MultiDiGraph(crs=3857)
    graph.add_node(10, x=0.0, y=0.0)
    graph.add_node(11, x=1.0, y=0.0)
    graph.add_node(12, x=2.0, y=0.0)
    graph.add_edge(10, 11, key=0, time_min=1.0, lanes=2)
    graph.add_edge(11, 12, key=0, time_min=1.0, lanes=2)
    graph.add_edge(12, 11, key=0, time_min=1.0, lanes=2)
    graph.add_edge(11, 10, key=0, time_min=1.0, lanes=2)

    blocks_to_nodes.to_pickle(tmp_path / "blocks_to_nodes.pickle")
    nodes_to_nodes.to_pickle(tmp_path / "nodes_to_nodes.pickle")
    nx.write_graphml(graph, tmp_path / "graph_drive.graphml")

    return blocks


def test_road_congestion_tool_is_registered_with_branch_contract(tmp_path: Path) -> None:
    tool = _tool(tmp_path)

    assert "OD-матрицу" in tool.description
    schema = tool.args_schema.model_json_schema()
    assert schema["properties"]["accessibility"]["default"] == 10.0
    assert "max_trips" in schema["properties"]


def test_road_congestion_reports_missing_branch_inputs(tmp_path: Path, monkeypatch) -> None:
    state = {
        "blocks": pd.DataFrame(
            {
                "population": [1],
                "land_use": ["RESIDENTIAL"],
                "site_area": [1.0],
                "count_shop": [1],
            },
            index=pd.Index([1], name="block_id"),
        )
    }
    result = _tool(tmp_path, state).invoke({})

    assert result.startswith("Ошибка:")
    assert "blocks_to_nodes" in result
    assert "blocks_to_nodes.pickle" in result


def test_road_congestion_stops_before_assignment_when_trip_budget_exceeded(
    tmp_path: Path, monkeypatch
) -> None:
    state = {
        "blocks": pd.DataFrame(
            {
                "population": [10],
                "land_use": ["RESIDENTIAL"],
                "site_area": [1.0],
                "count_shop": [1],
            },
            index=pd.Index([1], name="block_id"),
        )
    }
    blocks_to_nodes = pd.DataFrame(
        [[1.0, 2.0]],
        index=pd.Index([1], name="block_id"),
        columns=pd.Index([10, 11], name="node_id"),
        dtype="float32",
    )
    nodes_to_nodes = pd.DataFrame(
        [[0.0, 1.0], [1.0, 0.0]],
        index=pd.Index([10, 11], name="node_id"),
        columns=pd.Index([10, 11], name="node_id"),
        dtype="float32",
    )
    graph = nx.MultiDiGraph(crs=3857)
    graph.add_node(10, x=0.0, y=0.0)
    graph.add_node(11, x=1.0, y=0.0)
    graph.add_edge(10, 11, time_min=1.0, lanes=1)
    graph.add_edge(11, 10, time_min=1.0, lanes=1)

    monkeypatch.setattr(
        "blocksnet_agent.tools.network._load_road_congestion_inputs",
        lambda _: (blocks_to_nodes, nodes_to_nodes, graph),
    )

    # Vendor import is the real entry point after R3. Pre-R3 the import fails
    # (module not present yet) — this is the expected red state, see R1.
    # The tool binds ``origin_destination_matrix`` via
    # ``from blocksnet_agent.vendor.road_congestion import ...``, so the
    # bound name lives in ``blocksnet_agent.tools.network``. Patch that, not
    # the package attribute, so the tool's local binding sees the fake.
    import blocksnet_agent.tools.network as net_mod

    def fake_od(*args, **kwargs):
        return pd.DataFrame(
            [[0, 6], [5, 0]],
            index=pd.Index([10, 11], name="node_id"),
            columns=pd.Index([10, 11], name="node_id"),
            dtype="int64",
        )

    monkeypatch.setattr(net_mod, "origin_destination_matrix", fake_od)

    result = _tool(tmp_path, state).invoke({"max_trips": 10})

    assert "11 поездок" in result
    assert "max_trips=10" in result


def test_road_congestion_happy_path_runs_real_metric(tmp_path: Path) -> None:
    """End-to-end: real origin_destination_matrix + real road_congestion.

    MUST FAIL on PyPI-only blocksnet (current env, pre-R3) with a
    ``congestion_level`` KeyError; MUST PASS after vendoring the metric in R3.
    """
    blocks = _make_inputs(tmp_path)
    state = {"blocks": blocks}
    result = _tool(tmp_path, state).invoke({"max_trips": 100_000, "accessibility": 10.0})

    assert not result.startswith("Ошибка:"), result
    assert "nan" not in result
    # The summary lists the per-edge frame columns ``intensity``, ``capacity``,
    # ``congestion_level`` and the headline ``congestion_level:``.
    assert "capacity" in result
    assert "congestion_level" in result
    assert "intensity" in result
    assert "OD и дорожная загруженность вычислены" in result


def test_road_congestion_summary_matches_edge_contract() -> None:
    """_road_congestion_summary consumes the post-assignment edge frame.

    Independent of the tool wiring: directly construct an edges GeoDataFrame
    matching the contracted schema and confirm the summary respects it.
    """
    edges = pd.DataFrame(
        {
            "intensity": [10.0, 5.0, 0.0],
            "capacity": [1900.0, 1900.0, 1000.0],
            "congestion_level": [10 / 1900, 5 / 1900, 0.0],
        },
        index=pd.MultiIndex.from_tuples([(10, 11), (11, 12), (12, 10)]),
    )
    summary = _road_congestion_summary(edges, total_trips=15)
    assert "поездок=15" in summary
    assert "перегруженных рёбер (level>1)=0" in summary
    assert "мин=0.0000" in summary
    assert math.isfinite(0.0)
    assert "intensity" in summary


def test_road_congestion_summary_includes_lossy_lane_count() -> None:
    """R6: lossy ``lanes`` parsing is reported in the summary."""
    edges = pd.DataFrame(
        {
            "intensity": [0.0],
            "capacity": [1000.0],
            "congestion_level": [0.0],
        },
        index=pd.MultiIndex.from_tuples([(10, 11)]),
    )
    summary = _road_congestion_summary(edges, total_trips=0, lossy_lane_edges=2)
    assert "Рёбер с лоссовым разбором lanes" in summary
    assert "2" in summary.split("Рёбер с лоссовым разбором lanes")[1].split(".")[0]


def test_road_congestion_rejects_lanes_above_eight(tmp_path: Path) -> None:
    """R6: lanes > 8 must fail before the heavy assignment loop."""
    blocks = _make_inputs(tmp_path)
    state = {"blocks": blocks}
    graph_after = nx.read_graphml(
        tmp_path / "graph_drive.graphml", node_type=int, force_multigraph=True
    )
    for _, _, _, data in graph_after.edges(keys=True, data=True):
        data["lanes"] = 9
    nx.write_graphml(graph_after, tmp_path / "graph_drive.graphml")

    result = _tool(tmp_path, state).invoke({})
    assert result.startswith("Ошибка:")
    assert "lanes вне поддерживаемого диапазона 1..8" in result


def test_road_congestion_normalizes_lanes_zero_and_string_list(tmp_path: Path) -> None:
    """R6: ``lanes=0`` and ``lanes="3;2"`` are accepted (lossy parsing noted)."""
    blocks = _make_inputs(tmp_path)
    state = {"blocks": blocks}
    graph_after = nx.read_graphml(
        tmp_path / "graph_drive.graphml", node_type=int, force_multigraph=True
    )
    for u, v, _key, data in graph_after.edges(keys=True, data=True):
        if (u, v) == (10, 11):
            data["lanes"] = 0
        elif (u, v) == (11, 12):
            data["lanes"] = "3;2"
    nx.write_graphml(graph_after, tmp_path / "graph_drive.graphml")

    result = _tool(tmp_path, state).invoke({"max_trips": 100_000})
    assert not result.startswith("Ошибка:"), result
    assert "Рёбер с лоссовым разбором lanes" in result


def test_road_congestion_writes_sparse_od_top_pairs(tmp_path: Path) -> None:
    """R7: ``origin_destination_matrix.csv`` is sparse (top-N), not the full
    N×N matrix."""
    blocks = _make_inputs(tmp_path)
    state = {"blocks": blocks}
    result = _tool(tmp_path, state).invoke({"max_trips": 100_000, "od_top_pairs": 5})
    assert not result.startswith("Ошибка:"), result
    csv_path = tmp_path / "origin_destination_matrix.csv"
    assert csv_path.exists()
    # 3 nodes ⇒ full matrix has 9 entries; we asked for top-5 → at most 5 lines
    lines = csv_path.read_text().strip().splitlines()
    assert len(lines) - 1 <= 5  # minus the header
    # The full OD matrix is still in state for programmatic use.
    assert "origin_destination_matrix" in state

# --- Regressions found while verifying the R1-R8 implementation -------------


def test_vendored_diversity_rejects_a_list_of_service_tables() -> None:
    """A list must fail loudly, never silently keep only the first table.

    Upstream annotates ``services_count_dfs`` as ``list[pd.DataFrame]`` ("one
    per service category"), but ``shannon_diversity`` actually requires a
    blocks-shaped frame, so upstream raises on a list. An earlier vendored
    revision "helpfully" took ``[0]``, which turned that loud failure into a
    wrong Shannon index computed from the first table alone.
    """
    from blocksnet_agent.vendor.road_congestion.od_core import _calculate_diversity

    shops = pd.DataFrame({"count_shop": [3, 5]}, index=[101, 102])
    schools = pd.DataFrame({"count_school": [7, 9]}, index=[101, 102])
    blocks = pd.DataFrame({"site_area": [100.0, 80.0]}, index=[101, 102])

    with pytest.raises(AttributeError):
        _calculate_diversity(blocks.copy(), [shops, schools])


def test_vendored_diversity_accepts_one_aggregated_frame() -> None:
    """The shape the tool actually passes: one frame with every count_ column.

    ``blocks_df`` arrives already validated by ``BlocksSchema`` (pandera
    ``strict="filter"``), so it carries no ``count_*`` columns of its own —
    that is what keeps the ``join`` below from colliding.
    """
    from blocksnet.analysis.services import services_count
    from blocksnet_agent.vendor.road_congestion.od_core import _calculate_diversity

    services = pd.DataFrame(
        {"count_shop": [3, 5], "count_school": [7, 9]}, index=[101, 102]
    )
    validated_blocks = pd.DataFrame({"site_area": [100.0, 80.0]}, index=[101, 102])
    out = _calculate_diversity(validated_blocks, services_count(services))

    # Both service types contribute: count is the row-wise sum, not just shops.
    assert out["count"].tolist() == [10, 14]


def test_sparse_od_writer_does_not_materialise_the_full_matrix() -> None:
    """R7: peak memory must scale with sparsity, not with N².

    A whole-matrix ``stack()`` peaked at 612 MB on this input (9M cells, two
    non-zero entries), which extrapolates to ~61 GB at 30k nodes.
    """
    import tempfile
    import tracemalloc

    n = 3000
    od = pd.DataFrame(np.zeros((n, n), dtype="int64"))
    od.iloc[0, 1] = 5
    od.iloc[2, 3] = 7
    out = Path(tempfile.mkdtemp()) / "od.csv"

    tracemalloc.start()
    _save_sparse_od(od, out, top_n=200)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < 100 * 10**6, f"peak {peak / 1e6:.0f} MB — full-matrix temporary is back"

    rows = out.read_text().strip().splitlines()
    assert rows[0] == "origin,destination,trips"
    assert len(rows) - 1 == 2  # only the two non-zero pairs
    assert rows[1].endswith(",7")  # sorted by trips, descending
    assert rows[2].endswith(",5")


def test_sparse_od_writer_keeps_global_top_n_across_chunks() -> None:
    """Chunked scanning must not lose the global maximum to per-chunk trimming."""
    import tempfile

    n = _OD_SCAN_CHUNK_ROWS * 3  # forces three chunks
    od = pd.DataFrame(np.zeros((n, n), dtype="int64"))
    od.iloc[0, 1] = 10  # chunk 0
    od.iloc[_OD_SCAN_CHUNK_ROWS, 2] = 900  # chunk 1 — the global maximum
    od.iloc[_OD_SCAN_CHUNK_ROWS * 2, 3] = 50  # chunk 2
    out = Path(tempfile.mkdtemp()) / "od.csv"

    _save_sparse_od(od, out, top_n=2)

    rows = out.read_text().strip().splitlines()
    assert len(rows) - 1 == 2
    assert rows[1].endswith(",900"), rows
    assert rows[2].endswith(",50"), rows
