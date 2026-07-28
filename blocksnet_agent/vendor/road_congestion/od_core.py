"""Vendored metric: origin_destination_matrix.

Source: aimclub/blocksnet, branch ``feat/road_congestion``, commit ``3a2ea5f``.
File: ``blocksnet/analysis/network/origin_destination/core.py`` (256 lines).
Vendored on: 2026-07-28.
Upstream URL: https://github.com/aimclub/blocksnet/blob/3a2ea5f/blocksnet/analysis/network/origin_destination/core.py

Original BSD 3-Clause license follows; copyright is preserved per the upstream
LICENSE (see ``LICENSE.blocksnet`` in this directory).

KNOWN LIMITATION (carried from upstream):
  - See ``research/road_congestion_skill_basis.md`` for the full review.

CHANGES vs. upstream:
  - Relative import ``from .schemas import BlocksSchema`` is preserved; the
    ``schemas`` module is vendored alongside as ``schemas.py``.
  - Public symbol ``origin_destination_matrix`` is re-exported via this module
    (and via ``blocksnet_agent.vendor.road_congestion.__init__``).
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
import geopandas as gpd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from loguru import logger
from blocksnet.enums import LandUse
from blocksnet.analysis.diversity.shannon.core import (
    shannon_diversity,
    SHANNON_DIVERSITY_COLUMN,
    COUNT_COLUMN,
)
from .schemas import BlocksSchema

DENSITY_COLUMN = "density"
LU_CONST_COLUMN = "lu_const"
ATTRACTIVENESS_COLUMN = "attractiveness"
POPULATION_COLUMN = "population"

LU_CONSTS = {
    LandUse.INDUSTRIAL: 0.25,
    LandUse.BUSINESS: 0.3,
    LandUse.SPECIAL: 0.1,
    LandUse.TRANSPORT: 0.1,
    LandUse.RESIDENTIAL: 0.1,
    LandUse.AGRICULTURE: 0.05,
    LandUse.RECREATION: 0.05,
}
DEFAULT_LU_CONST = 0.06

LU_TRIP_RATES = {
    LandUse.RESIDENTIAL: 1.0,
    LandUse.BUSINESS: 2.7,
    LandUse.INDUSTRIAL: 2.0,
    LandUse.SPECIAL: 1.2,
    LandUse.TRANSPORT: 1.0,
    LandUse.RECREATION: 1.4,
    LandUse.AGRICULTURE: 0.2,
}
DEFAULT_TRIP_RATE = 1.0

DEFAULT_ACCESSIBILITY = 10


def _round_probabilistic_row_to_int(prob_row: pd.Series, trips: int) -> pd.Series:
    raw = prob_row.to_numpy(dtype=float) * float(trips)
    floored = np.floor(raw).astype("int64")
    remainder = int(trips - floored.sum())

    if remainder > 0:
        fractional = raw - floored
        order = np.argsort(-fractional, kind="mergesort")
        floored[order[:remainder]] += 1

    return pd.Series(floored, index=prob_row.index, dtype="int64")


def _integerize_origin_constrained_od(od_prob_mx: pd.DataFrame, demand: pd.Series) -> pd.DataFrame:
    od_int = pd.DataFrame(0, index=od_prob_mx.index, columns=od_prob_mx.columns, dtype="int64")
    demand_int = demand.round().clip(lower=0).astype("int64")

    for origin, trips in demand_int.items():
        trips = int(trips)
        if trips <= 0:
            continue

        prob_row = od_prob_mx.loc[origin].astype(float)
        row_sum = float(prob_row.sum())

        if row_sum <= 0.0:
            prob_row[:] = 0.0
            if origin in prob_row.index:
                prob_row.loc[origin] = 1.0
        else:
            prob_row = prob_row / row_sum

        od_int.loc[origin] = _round_probabilistic_row_to_int(prob_row, trips)

    return od_int


def _calculate_nodes_weights(
    blocks_df: gpd.GeoDataFrame,
    acc_mx: pd.DataFrame,
    accessibility: float,
    trip_rates: dict,
) -> pd.DataFrame:
    logger.info("Identifying nearest nodes to blocks")
    acc_mx = acc_mx.replace(0, 0.1)
    acc_mask = acc_mx <= accessibility
    acc_mask = acc_mask | acc_mx.eq(acc_mx.min(axis=1), axis=0)

    logger.info("Calculating weights")
    weights_mx = pd.DataFrame(0.0, index=acc_mx.index, columns=acc_mx.columns)
    weights_mx[acc_mask] = 1.0 / acc_mx[acc_mask]
    weights_sum = weights_mx.sum(axis=1)
    weights_mx = weights_mx.div(weights_sum, axis=0)

    effective_population = blocks_df[POPULATION_COLUMN] * blocks_df.land_use.map(
        lambda lu: trip_rates.get(lu, DEFAULT_TRIP_RATE)
    )

    logger.info("Distributing")
    nodes_df = pd.DataFrame(index=acc_mx.columns)
    nodes_df[ATTRACTIVENESS_COLUMN] = weights_mx.mul(blocks_df[ATTRACTIVENESS_COLUMN], axis=0).sum(axis=0)
    nodes_df[POPULATION_COLUMN] = weights_mx.mul(effective_population, axis=0).sum(axis=0)
    return nodes_df


def _calculate_diversity(blocks_df: pd.DataFrame, services_count_dfs) -> pd.DataFrame:
    """Compute Shannon diversity + density per block.

    Passes ``services_count_dfs`` straight through, exactly as upstream does.

    Upstream's annotation says ``list[pd.DataFrame]``, but
    ``blocksnet.analysis.diversity.shannon.core.shannon_diversity`` actually
    requires a blocks-shaped DataFrame carrying ``count_*`` columns (it calls
    ``services_count`` on the argument itself). Passing a list therefore fails
    loudly upstream, and it must keep failing loudly here: silently taking
    ``[0]`` would drop every service table but the first and return a wrong
    Shannon index instead of an error. Callers pass one aggregated frame —
    ``services_count(blocks)`` already merges all ``count_*`` columns.
    """
    logger.info("Calculating diversity and density")
    diversity_df = shannon_diversity(services_count_dfs)
    blocks_df = blocks_df.join(diversity_df)
    blocks_df[DENSITY_COLUMN] = blocks_df[COUNT_COLUMN] / blocks_df.site_area
    return blocks_df


def _calculate_attractiveness(blocks_df: pd.DataFrame, lu_consts: dict) -> pd.DataFrame:
    logger.info("Calculating attractiveness")
    blocks_df = blocks_df.copy()
    blocks_df[LU_CONST_COLUMN] = blocks_df.land_use.apply(lambda lu: lu_consts.get(lu, DEFAULT_LU_CONST))
    scaler = MinMaxScaler()
    columns = [DENSITY_COLUMN, SHANNON_DIVERSITY_COLUMN, LU_CONST_COLUMN]
    blocks_df[columns] = scaler.fit_transform(blocks_df[columns])
    blocks_df[ATTRACTIVENESS_COLUMN] = (
        blocks_df[DENSITY_COLUMN] + blocks_df[SHANNON_DIVERSITY_COLUMN] + blocks_df[LU_CONST_COLUMN]
    )
    return blocks_df


def _calculate_od_mx(nodes_df: pd.DataFrame, acc_mx: pd.DataFrame) -> pd.DataFrame:
    logger.info("Calculating origin destination matrix")
    acc_mx = acc_mx.replace(0, np.nan)

    gravity_weights = (1.0 / acc_mx).mul(nodes_df[ATTRACTIVENESS_COLUMN], axis=1).fillna(0.0)

    empty_rows = gravity_weights.sum(axis=1).eq(0.0)
    for node_id in gravity_weights.index[empty_rows]:
        gravity_weights.loc[node_id, node_id] = 1.0

    row_sums = gravity_weights.sum(axis=1).replace(0.0, np.nan)
    od_prob_mx = gravity_weights.div(row_sums, axis=0).fillna(0.0)

    return _integerize_origin_constrained_od(od_prob_mx, nodes_df[POPULATION_COLUMN])


def _validate_input(blocks_df: pd.DataFrame, blocks_to_nodes_mx: pd.DataFrame, nodes_to_nodes_mx: pd.DataFrame):
    logger.info("Validating input data")
    if not all(blocks_df.index == blocks_to_nodes_mx.index):
        raise ValueError("blocks_df index and blocks_to_nodes_mx index must match")
    if not all(blocks_to_nodes_mx.columns == nodes_to_nodes_mx.index):
        raise ValueError("blocks_to_nodes_mx columns and nodes_to_nodes index must match")
    if not all(nodes_to_nodes_mx.index == nodes_to_nodes_mx.columns):
        raise ValueError("nodes_to_nodes_mx index and columns must match")


def origin_destination_matrix(
    blocks_df: pd.DataFrame,
    blocks_to_nodes_mx: pd.DataFrame,
    nodes_to_nodes_mx: pd.DataFrame,
    services_count_dfs: list,
    accessibility: float = DEFAULT_ACCESSIBILITY,
    lu_consts: dict = None,
    lu_trip_rates: dict = None,
) -> pd.DataFrame:
    """Build an origin-constrained integer OD matrix (gravity model)."""
    if lu_consts is None:
        lu_consts = LU_CONSTS
    if lu_trip_rates is None:
        lu_trip_rates = LU_TRIP_RATES

    blocks_df = BlocksSchema(blocks_df)
    _validate_input(blocks_df, blocks_to_nodes_mx, nodes_to_nodes_mx)

    blocks_df = _calculate_diversity(blocks_df, services_count_dfs)
    blocks_df = _calculate_attractiveness(blocks_df, lu_consts)

    nodes_gdf = _calculate_nodes_weights(blocks_df, blocks_to_nodes_mx, accessibility, lu_trip_rates)

    return _calculate_od_mx(nodes_gdf, nodes_to_nodes_mx)