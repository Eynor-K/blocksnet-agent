"""Vendored metric: road_congestion (assignment + edge-level load).

Source: aimclub/blocksnet, branch ``feat/road_congestion``, commit ``3a2ea5f``.
File: ``blocksnet/analysis/network/road_congestion/core.py`` (211 lines).
Vendored on: 2026-07-28.
Upstream URL: https://github.com/aimclub/blocksnet/blob/3a2ea5f/blocksnet/analysis/network/road_congestion/core.py

Original BSD 3-Clause license follows; copyright is preserved per the upstream
LICENSE (see ``LICENSE.blocksnet`` in this directory).

KNOWN LIMITATIONS (carried from upstream, see research/road_congestion_skill_basis.md):
  - Discrete trip-by-trip Dijkstra assignment; ``O(total_trips * Dijkstra)``.
  - Multigraph oversaturation removes only the routing edge key, not the output
    edge; ``congestion_level > 1.0`` is the final load, not an error.
  - ``LANE_COEF`` is defined for lanes 1..8; the docstring says 1..6. ``lanes=9``
    raises ``KeyError`` in ``_get_capacity_by_lanes``. Tool pre-validates
    ``lanes in 1..8`` before calling (see R6).
  - FIXME upstream: multidigraph edges split congestion.
"""

# BSD 3-Clause License
#
# Copyright (c) 2023, iduprojects
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.

import pandas as pd
import networkx as nx
import numpy as np
from blocksnet.relations.accessibility import validate_accessibility_graph
from blocksnet_agent.vendor.road_congestion.schemas import validate_od_matrix
from tqdm import tqdm
from blocksnet.config import log_config
from loguru import logger

CONGESTION_KEY = "congestion"

LANE_CAPACITY = 1000

LANE_COEF = {
    1: 1.0,
    2: 0.95,
    3: 0.90,
    4: 0.86,
    5: 0.84,
    6: 0.82,
    7: 0.80,
    8: 0.78,
}


def _get_capacity_by_lanes(lanes):
    return LANE_CAPACITY * LANE_COEF[lanes] * lanes


def _normalize_lanes(G: nx.Graph, default: int = 1) -> nx.Graph:
    for _, _, data in G.edges(data=True):
        raw = data.get("lanes", None)

        if isinstance(raw, list):
            raw = min(raw) if raw else None

        if isinstance(raw, str):
            s = raw.strip()
            for sep in [";", "|", ","]:
                if sep in s:
                    s = s.split(sep)[0].strip()
                    break
            raw = s

        try:
            lanes = int(float(raw))
        except (TypeError, ValueError):
            lanes = default

        if lanes < 1:
            lanes = default

        data["lanes"] = lanes

    return G


def _add_intensity(G: nx.Graph, intensity_default: float = 0) -> nx.Graph:
    for _, _, data in G.edges(data=True):
        data["intensity"] = intensity_default

    return G


def _add_capacity(G: nx.Graph) -> nx.Graph:
    for _, _, data in G.edges(data=True):
        lanes = data.get("lanes", 1)
        data["capacity"] = _get_capacity_by_lanes(lanes)
    return G


def _preprocess_graph(G: nx.Graph) -> nx.Graph:
    """Normalize lanes, init intensity, compute capacity.

    NOTE: upstream typo (``_peprocess_graph``) is fixed here; the rename is
    internal and the call sites below use the corrected name.
    """
    H = G.copy()
    _normalize_lanes(H)
    _add_intensity(H)
    _add_capacity(H)
    return H


def road_congestion(od_mx: pd.DataFrame, G: nx.MultiDiGraph, weight_key: str = "time_min") -> nx.MultiDiGraph:
    """Discrete trip-by-trip assignment with per-edge congestion_level.

    See module docstring for the full contract and known limitations.
    """
    validate_od_matrix(od_mx, G)
    validate_accessibility_graph(G, weight_key)

    logger.info("Preprocessing graph")
    H = _preprocess_graph(G)
    graph_congestion = H.copy()
    graph_routing = H.copy()

    for _, _, k, data in graph_congestion.edges(keys=True, data=True):
        data["intensity"] = 0.0

    logger.info("Calculating shortest paths")
    for i in tqdm(od_mx.index, disable=log_config.disable_tqdm):
        for j, demand in od_mx.loc[i].items():
            if i == j or demand <= 0:
                continue

            trips = int(round(float(demand)))

            for _ in range(trips):
                try:
                    route = nx.shortest_path(graph_routing, source=i, target=j, weight=weight_key, method="dijkstra")
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    break

                for u, v in zip(route[:-1], route[1:]):
                    k = min(graph_routing[u][v], key=lambda kk: graph_routing[u][v][kk].get(weight_key, np.inf))

                    graph_routing[u][v][k]["intensity"] += 1.0
                    graph_congestion[u][v][k]["intensity"] += 1.0

                    capacity = float(graph_routing[u][v][k]["capacity"])
                    congestion_level = graph_routing[u][v][k]["intensity"] / max(capacity, 1e-9)
                    if congestion_level > 1.0:
                        graph_routing.remove_edge(u, v, key=k)

    logger.info("Computing congestion level")
    for _, _, _, data in graph_congestion.edges(keys=True, data=True):
        data["congestion_level"] = data["intensity"] / max(data["capacity"], 1e-9)

    return graph_congestion