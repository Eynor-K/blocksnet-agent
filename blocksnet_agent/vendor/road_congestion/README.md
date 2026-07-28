# Vendored: aimclub/blocksnet ``feat/road_congestion`` @ 3a2ea5f

This sub-package contains a vendored copy of two metrics from
[aimclub/blocksnet](https://github.com/aimclub/blocksnet) at branch
`feat/road_congestion`, commit `3a2ea5f`:

- `origin_destination_matrix` (and its private helpers) — from
  `blocksnet/analysis/network/origin_destination/core.py`.
- `road_congestion` (and its private helpers) — from
  `blocksnet/analysis/network/road_congestion/core.py`.
- The accompanying `BlocksSchema` and `validate_od_matrix` —
  from `blocksnet/analysis/network/origin_destination/schemas.py`.

## Why vendored

`pyproject.toml` used to pin the entire `blocksnet` dependency on the
`feat/road_congestion` branch to access these two functions. That made every
other tool (32 of them) depend on an unreleased branch, with the reproducibility
risk that entails. The metric is the only consumer; vendoring it lets us return
to a released `blocksnet` from PyPI and own ~470 lines of well-reviewed code.

The behavior is byte-identical to upstream modulo:

1. A renamed typo (`_peprocess_graph` → `_preprocess_graph`); the call sites
   were updated.
2. `from ..origin_destination import validate_od_matrix` was rewritten to
   `from blocksnet_agent.vendor.road_congestion.schemas import
   validate_od_matrix` to avoid a circular import once the module is no longer
   inside the `blocksnet.analysis.network` tree.

## Known limitations

Carried verbatim from upstream — see `research/road_congestion_skill_basis.md`
for the full review.

- Discrete trip-by-trip Dijkstra assignment: `O(total_trips * Dijkstra)`.
  For OD > ~50 000 the tool's trip-budget guard returns a clear message.
- The output graph keeps the full edge set; oversaturated multigraph keys are
  removed only from the routing graph. `congestion_level > 1.0` is the final
  load, not an error.
- `_get_capacity_by_lanes` `KeyError`s on `lanes > 8`; the tool pre-validates
  `1 ≤ lanes ≤ 8` before calling. `_normalize_lanes` clamps `lanes < 1` to
  `1`.
- `services_count_dfs` argument is currently passed positionally; `blocksnet`
  renamed the parameter internally from `services_count` to `services_count`
  on the call site. The contract here uses the list form `[*count_df]` —
  see `_calculate_diversity` in `od_core.py`.

## License

`LICENSE.blocksnet` is the original BSD 3-Clause text. Copyright is preserved
in every vendored file. This project is MIT-licensed at the top level; BSD
3-Clause is compatible.