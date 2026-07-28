"""Vendored road-congestion metric (aimclub/blocksnet @ feat/road_congestion).

Re-exports the two public functions ``origin_destination_matrix`` and
``road_congestion`` together with their public constants. Provenance and
BSD-3-Clause copyright are in the per-file docstrings; upstream is commit
``3a2ea5f``.

Fidelity to upstream — behaviour is unchanged, and every difference is listed
here, so a reader never has to diff to trust this copy. An AST comparison of
all 14 upstream functions leaves exactly the last two items below:

* imports resolved (``from ..origin_destination`` / ``from .schemas`` now point
  at the vendored ``schemas`` module);
* ``_peprocess_graph`` renamed to ``_preprocess_graph`` (upstream typo); the
  single call site is updated with it;
* ``_get_capacity_by_lanes`` returns its expression directly instead of via a
  local variable;
* long upstream docstrings condensed; the contract they described lives in the
  per-file module docstrings and in ``research/road_congestion_skill_basis.md``;
* generic annotations relaxed (``dict[LandUse, float]`` -> ``dict``,
  ``list[pd.DataFrame]`` -> ``list``) and the two mutable dict defaults on
  ``origin_destination_matrix`` replaced with ``None`` sentinels resolved in the
  body — same effective defaults, no shared-mutable-default hazard.

No behavioural difference is intended. If you change that, say so here.
"""

from .od_core import (
    origin_destination_matrix,
    LU_CONSTS,
    LU_TRIP_RATES,
    DEFAULT_ACCESSIBILITY,
    DEFAULT_LU_CONST,
    DEFAULT_TRIP_RATE,
)
from .rc_core import (
    road_congestion,
    LANE_CAPACITY,
    LANE_COEF,
)
from .schemas import BlocksSchema, validate_od_matrix

__all__ = [
    "origin_destination_matrix",
    "road_congestion",
    "LU_CONSTS",
    "LU_TRIP_RATES",
    "DEFAULT_ACCESSIBILITY",
    "DEFAULT_LU_CONST",
    "DEFAULT_TRIP_RATE",
    "LANE_CAPACITY",
    "LANE_COEF",
    "BlocksSchema",
    "validate_od_matrix",
]