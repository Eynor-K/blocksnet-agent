"""Vendored pandera schema + validate_od_matrix helper.

Source: aimclub/blocksnet, branch ``feat/road_congestion``, commit ``3a2ea5f``.
File: ``blocksnet/analysis/network/origin_destination/schemas.py`` (20 lines).
Vendored on: 2026-07-28.
Upstream URL: https://github.com/aimclub/blocksnet/blob/3a2ea5f/blocksnet/analysis/network/origin_destination/schemas.py

BSD 3-Clause License — see ``LICENSE.blocksnet`` in this directory.
"""

# BSD 3-Clause License
#
# Copyright (c) 2023, iduprojects

import shapely
import pandas as pd
import networkx as nx
from pandera import Field
from pandera.typing import Series
from blocksnet.utils.validation import GdfSchema, LandUseSchema


class BlocksSchema(LandUseSchema):
    population: Series[int] = Field(ge=0)
    site_area: Series[float] = Field(ge=0)


def validate_od_matrix(od_mx: pd.DataFrame, graph: nx.Graph):
    if not isinstance(od_mx, pd.DataFrame):
        raise ValueError("Origin destination matrix must be an instance of pd.DataFrame")
    if not all(od_mx.index == od_mx.columns):
        raise ValueError("Origin destination matrix index and columns must match")
    if not od_mx.index.isin(graph.nodes).all():
        raise ValueError("Origin destination matrix index must be contained in graph nodes labels")