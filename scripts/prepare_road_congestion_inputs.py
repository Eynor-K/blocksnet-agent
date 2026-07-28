"""Build the road-congestion inputs expected by ``compute_road_congestion``.

Reads ``data/blocks_with_services.gpkg`` (the input the rest of the pipeline
already uses) and writes into the same ``data_dir``:

- ``blocks_to_nodes.pickle`` — block → nearest drive/walk node generalized
  cost (float32, m×N matrix).
- ``nodes_to_nodes.pickle`` — square, N×N drive-time matrix (float32).
- ``graph_drive.graphml`` — drive MultiDiGraph with int EPSG, x/y nodes,
  ``time_min`` and ``lanes`` edges.

This is the deterministic preparation step called out in the
``docs/dev/plans/road_congestion.md`` plan (R4).

Usage
-----

    python -m scripts.prepare_road_congestion_inputs \
        --data-dir data \
        --buffer-m 0  # optional: clip blocks to a buffer around their centroid

Without arguments it uses the defaults expected by ``RUN.md``:

- ``data_dir = data``
- ``blocks_path = blocks_with_services.gpkg``
- ``buffer_m = 0`` (whole dataset)

The script validates everything the tool will require and refuses to write
half-baked inputs, so the tool never sees a ``KeyError`` or
``FileNotFoundError`` from this preparation.

NOTE: a full run on a real OSM-based city can take many minutes because
``get_accessibility_graph`` queries Overpass. Run offline or with a pre-built
``blocks_with_services.gpkg`` for reproducible timings.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd

REQUIRED_BLOCK_COLUMNS = ("population", "land_use", "site_area")
REQUIRED_COUNT_PREFIX = "count_"


def _project_to_utm(blocks: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Project blocks to a metric CRS so we can compute buffers in metres."""
    if blocks.crs is None:
        raise ValueError("blocks CRS is None; cannot project to metric")
    if not blocks.crs.is_projected:
        blocks = blocks.to_crs(blocks.estimate_utm_crs())
    return blocks


def _load_blocks(data_dir: Path, blocks_path: str | None) -> gpd.GeoDataFrame:
    candidate = data_dir / (blocks_path or "blocks_with_services.gpkg")
    if not candidate.exists():
        raise FileNotFoundError(
            f"не найден {candidate}. Положи blocks_with_services.gpkg в data_dir."
        )
    blocks = gpd.read_file(candidate)
    if blocks.empty:
        raise ValueError(f"{candidate} пуст — инструменту нужны ≥1 квартал")
    missing = [c for c in REQUIRED_BLOCK_COLUMNS if c not in blocks.columns]
    if missing:
        raise ValueError(f"blocks_with_services не содержит нужных колонок: {missing}")
    if not any(c.startswith(REQUIRED_COUNT_PREFIX) for c in blocks.columns):
        raise ValueError(
            f"blocks_with_services без {REQUIRED_COUNT_PREFIX}* колонок — "
            "services_count нечего считать"
        )
    return _project_to_utm(blocks)


def _validate_graph(graph: nx.MultiDiGraph, expected_nodes: set[int]) -> None:
    crs = graph.graph.get("crs")
    if not isinstance(crs, int):
        raise ValueError(f"graph.graph['crs'] должно быть int EPSG, не {type(crs).__name__}")
    nodes = set(graph.nodes)
    if not expected_nodes <= nodes:
        missing = sorted(expected_nodes - nodes)[:5]
        raise ValueError(f"drive-граф не содержит OD-узлов: {missing}")
    for u, v, data in graph.edges(data=True):
        if "time_min" not in data:
            raise ValueError(f"ребро ({u}, {v}) без time_min — iduedu не вернул вес")
    bad_lanes = []
    for u, v, data in graph.edges(data=True):
        raw = data.get("lanes", 1)
        try:
            lanes = int(float(raw))
        except (TypeError, ValueError):
            lanes = -1
        if not (1 <= lanes <= 8):
            bad_lanes.append((u, v, raw))
    if bad_lanes:
        raise ValueError(
            f"lanes вне 1..8 на {len(bad_lanes)} рёбрах (пример: {bad_lanes[:3]}); "
            "compute_road_congestion отвергнет граф — поправь входной gpkg"
        )


def _validate_matrices(
    blocks_to_nodes: pd.DataFrame, nodes_to_nodes: pd.DataFrame, blocks: gpd.GeoDataFrame
) -> None:
    if set(blocks.index) != set(blocks_to_nodes.index):
        raise ValueError(
            "индекс blocks должен совпадать с blocks_to_nodes.index "
            "(перезапусти с тем же gpkg)"
        )
    if not nodes_to_nodes.index.equals(nodes_to_nodes.columns):
        raise ValueError("nodes_to_nodes должна быть квадратной")
    if list(nodes_to_nodes.columns) != list(blocks_to_nodes.columns):
        raise ValueError(
            "узлы blocks_to_nodes.columns и nodes_to_nodes.columns должны совпадать"
        )


def prepare(data_dir: Path) -> dict[str, Path]:
    """Run the full preparation. Returns the paths of the produced files."""
    from iduedu import get_adj_matrix_gdf_to_gdf
    from blocksnet.relations import get_accessibility_graph, accessibility_graph_to_gdfs

    blocks = _load_blocks(data_dir, blocks_path=None)
    print(f"[prepare] blocks: {len(blocks)}")

    # Walk graph: short distances for block→node distribution.
    graph_walk = get_accessibility_graph(blocks, "walk")
    graph_drive = get_accessibility_graph(
        blocks, "drive", additional_edgedata=["lanes"]
    )

    nodes_gdf, _ = accessibility_graph_to_gdfs(graph_drive)
    node_ids = list(nodes_gdf.index)
    print(f"[prepare] nodes: {len(node_ids)}")

    blocks_to_nodes = get_adj_matrix_gdf_to_gdf(
        blocks, nodes_gdf, graph_walk, weight="time_min", dtype="float32"
    )
    nodes_to_nodes = get_adj_matrix_gdf_to_gdf(
        nodes_gdf, nodes_gdf, graph_drive, weight="time_min", dtype="float32"
    )

    _validate_matrices(blocks_to_nodes, nodes_to_nodes, blocks)
    _validate_graph(graph_drive, set(node_ids))

    out_b2n = data_dir / "blocks_to_nodes.pickle"
    out_n2n = data_dir / "nodes_to_nodes.pickle"
    out_g = data_dir / "graph_drive.graphml"

    blocks_to_nodes.to_pickle(out_b2n)
    nodes_to_nodes.to_pickle(out_n2n)
    nx.write_graphml(graph_drive, out_g)

    sizes = {
        out_b2n: out_b2n.stat().st_size,
        out_n2n: out_n2n.stat().st_size,
        out_g: out_g.stat().st_size,
    }
    print(f"[prepare] wrote {out_b2n.name} ({sizes[out_b2n]} bytes)")
    print(f"[prepare] wrote {out_n2n.name} ({sizes[out_n2n]} bytes)")
    print(f"[prepare] wrote {out_g.name} ({sizes[out_g]} bytes)")
    return {"blocks_to_nodes": out_b2n, "nodes_to_nodes": out_n2n, "graph_drive": out_g}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=Path, help="директория с data/")
    args = parser.parse_args(argv)

    try:
        prepare(args.data_dir)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())