# Tech basis: blocksnet `feat/road_congestion` OD + road_congestion

Read-only research of `aimclub/blocksnet` @ branch `feat/road_congestion` (commit `3a2ea5f`).
Local clone (read-only): `/root/research/blocksnet-rc/blocksnet/`.

Source of truth: `https://github.com/aimclub/blocksnet/blob/feat/road_congestion/...`
Reference notebook: `https://github.com/aimclub/blocksnet/blob/feat/road_congestion/examples/analysis/network/od_and_rc.ipynb`

---

## 1. Modules in scope (verified paths)

All under `blocksnet/analysis/network/`:

| File | Exports / symbols | Role |
|---|---|---|
| `__init__.py` | re-exports `accessibility`, `connectivity`, `origin_destination`, `road_congestion`, `classification` | Package entry point |
| `origin_destination/__init__.py` | `origin_destination_matrix`, `validate_od_matrix` | Public API for OD |
| `origin_destination/core.py` | `origin_destination_matrix`, `_calculate_nodes_weights`, `_calculate_diversity`, `_calculate_attractiveness`, `_calculate_od_mx`, `_validate_input`, `_integerize_origin_constrained_od`, `_round_probabilistic_row_to_int`; constants `DENSITY_COLUMN`, `LU_CONST_COLUMN`, `ATTRACTIVENESS_COLUMN`, `POPULATION_COLUMN`, `LU_CONSTS`, `DEFAULT_LU_CONST`, `LU_TRIP_RATES`, `DEFAULT_TRIP_RATE`, `DEFAULT_ACCESSIBILITY` | Build integer OD matrix via origin-constrained gravity model |
| `origin_destination/schemas.py` | `BlocksSchema` (pandera, extends `LandUseSchema` with `population:int≥0`, `site_area:float≥0`); `validate_od_matrix(od_mx, graph)` — requires square OD, indices ⊂ `graph.nodes` | Input validation |
| `road_congestion/__init__.py` | `road_congestion` | Public API |
| `road_congestion/core.py` | `road_congestion(od_mx, G, weight_key="time_min")`; constants `CONGESTION_KEY`, `LANE_CAPACITY`, `LANE_COEF`; helpers `_get_capacity_by_lanes`, `_normalize_lanes`, `_add_intensity`, `_add_capacity`, `_peprocess_graph` | Trip-by-trip discrete assignment + congestion_level |

Required validations pulled from elsewhere (used by the two modules above):
- `blocksnet/relations/accessibility/graph/schemas.py` — `validate_accessibility_graph(graph, weight_key=WEIGHT_KEY)`. Requires: `graph.graph["crs"]` is int EPSG, every node has `x`/`y`, every edge has `weight_key` (default `"time_min"`).
- `blocksnet/relations/accessibility/graph/core.py` — `get_accessibility_graph(territory_gdf, graph_type: Literal["drive","walk","intermodal"], *args, **kwargs)`. Forwards to `iduedu`.
- `blocksnet/relations/accessibility/graph/utils.py` — `accessibility_graph_to_gdfs(graph) -> (nodes_gdf, edges_gdf)`.
- `blocksnet/analysis/services/count/core.py` — `services_count(blocks_df)` requires `count_*` columns (excluding `*_buildings`).
- `blocksnet/analysis/diversity/shannon/core.py` — `shannon_diversity`, `SHANNON_DIVERSITY_COLUMN`, `COUNT_COLUMN`. Internally re-uses `services_count`.

---

## 2. Data contracts (exact)

### 2.1 `blocks_df` (input to `origin_destination_matrix`)

Validated by `BlocksSchema` (pandera-based). Required columns:
- `geometry` (any shapely geom; CRS warning if not projected) — from `GdfSchema`.
- `land_use` — values coercible to `LandUse` enum: `RESIDENTIAL, BUSINESS, RECREATION, INDUSTRIAL, TRANSPORT, SPECIAL, AGRICULTURE` (case-insensitive parse).
- `population : int ≥ 0` (production side).
- `site_area : float ≥ 0` (used for service density).
- Implicitly needs `count_*` columns (excluding `*_buildings`) because `services_count` is called by `_calculate_diversity`.

Index must equal `blocks_to_nodes_mx.index`.

### 2.2 `blocks_to_nodes_mx` (DataFrame)

Square-or-rectangular matrix, blocks on rows, network nodes on columns. Values are generalized cost (e.g. walk time, minutes). Zeros in `_calculate_nodes_weights` are replaced by `0.1` before thresholding.

### 2.3 `nodes_to_nodes_mx` (DataFrame)

Strictly square, index == columns, all finite ≥ 0 (zeros treated as missing for gravity). Same node set as `blocks_to_nodes_mx.columns`.

### 2.4 `services_count_dfs` (list[DataFrame])

List of per-service count tables; fed into `shannon_diversity` (see `blocksnet/analysis/diversity/shannon/core.py`).

### 2.5 `od_mx` (output of OD; input to road_congestion)

- `pandas.DataFrame`, **integer dtype** (`int64`).
- `index == columns` (square, same node IDs as `nodes_to_nodes_mx`).
- `int64` row sums match each origin's distributed integer population.
- Validated by `validate_od_matrix`:
  - all `od_mx.index ⊂ graph.nodes`.

### 2.6 `G` (input to road_congestion; `nx.MultiDiGraph`)

Validated by `validate_accessibility_graph`:
- `graph.graph["crs"] : int` (EPSG code).
- Every node has `x`, `y` (projected coords).
- Every edge has `weight_key` attribute (default `"time_min"`).

`lanes` (edge attribute) is normalized inside `_normalize_lanes`:
- `list` → `min(list)` (or None if empty).
- `str` → strip; if contains `; | ,` take the first chunk; `int(float(raw))`.
- invalid / missing → `1`.
- final `lanes < 1` → `1`.

After preprocessing the returned graph has, on every edge:
- `lanes : int` (≥1)
- `capacity : float` = `LANE_CAPACITY * LANE_COEF[lanes] * lanes` (= `1000 * coef * lanes`).
- `intensity : float` (starts at 0; final value is number of assigned trips).
- `congestion_level : float` = `intensity / max(capacity, 1e-9)`.

Supported `LANE_COEF` is **1..6** (see `LANE_COEF = {1:1.0, 2:0.95, 3:0.90, 4:0.86, 5:0.84, 6:0.82}`); `7, 8` defined but docstring says lanes outside 1..6 raise unless `LANE_COEF` is extended.

---

## 3. Deterministic workflow (as run in `od_and_rc.ipynb`)

The reference notebook is the canonical end-to-end flow. 25 cells, no surprises, no extra config:

1. **Load blocks**: `blocks_gdf = pd.read_pickle('./../data/blocks.pickle')`.
2. **Filter to a local study area**: `ox.geocode_to_gdf('R1114252', by_osmid=True)` (OSM relation ID for an unspecified municipality — St. Petersburg district in the bundled data), then `blocks_gdf = blocks_gdf[blocks_gdf.intersects(polygon.union_all())]`.
3. **Build accessibility graphs (projected CRS)**:
   - `graph_drive = get_accessibility_graph(blocks_gdf, 'drive', additional_edgedata=["lanes"])`
   - `graph_walk = get_accessibility_graph(blocks_gdf, 'walk')`
4. **Extract nodes GeoDataFrame**: `nodes_gdf, _ = accessibility_graph_to_gdfs(graph_drive)`.
5. **Block-to-node matrix (walk)**: `blocks_to_nodes = get_adj_matrix_gdf_to_gdf(blocks_gdf, nodes_gdf, graph_walk, weight='time_min')`.
6. **Node-to-node matrix (drive)**: `nodes_to_nodes = get_adj_matrix_gdf_to_gdf(nodes_gdf, nodes_gdf, graph_drive, weight='time_min')`.
7. **Services count per block**: `count_df = services_count(blocks_gdf)` (uses `count_*` columns).
8. **OD matrix**: `od_mx = origin_destination_matrix(blocks_gdf, blocks_to_nodes, nodes_to_nodes, count_df)`.
9. **Sanity**: `od_mx.sum().sum()` should equal (approximately) the integerized total distributed population from step 4.
10. **Road congestion**: `graph_congestion = road_congestion(od_mx, graph_drive)` — default `weight_key="time_min"`.
11. **Extract edges for viz**: `_, edges_gdf = accessibility_graph_to_gdfs(graph_congestion)`.
12. **Plot**: `edges_gdf.plot('congestion_level', cmap="RdYlGn_r", legend=True, figsize=(8,5))`.

The notebook produces (per `raw.githubusercontent.com` extract):
- blocks: 2 rows × 137 columns (incl. service count columns + `land_use`).
- blocks-to-nodes / nodes-to-nodes: 5×712 / 712×712.
- counts: 5×61 (services).
- post-assignment edges show columns: `length_meter`, `time_min`, `geometry`, `lanes`, `intensity`, `capacity`, `congestion_level`.

---

## 4. Formulas & semantics (verbatim from source, no own math)

### 4.1 Node weights (block → node distribution)

`acc_mx` is `blocks_to_nodes_mx`. Zeros replaced by `0.1`. For each block, mask = `acc_mx ≤ accessibility` OR the per-row minimum (so the nearest node is always included). Then:

```
weights_mx[mask] = 1.0 / acc_mx[mask]
weights_mx      /= weights_mx.sum(axis=1)             # row-normalize
effective_population = block.population * block.land_use.map(lu_trip_rates)
nodes_df.attractiveness = weights_mx.T @ block.attractiveness
nodes_df.population     = weights_mx.T @ effective_population
```

### 4.2 Block-level attractiveness

- `density` = total service count / `site_area` (added by `_calculate_diversity`).
- `shannon_diversity` from `shannon_diversity(blocks_df)`.
- `lu_const` = `LU_CONSTS[land_use]` else `DEFAULT_LU_CONST` (0.06).
- MinMax-scale `density`, `shannon_diversity`, `lu_const`; sum → `attractiveness`.

Constants (from `origin_destination/core.py`):

```python
LU_CONSTS = {
  INDUSTRIAL: 0.25, BUSINESS: 0.30, SPECIAL: 0.10, TRANSPORT: 0.10,
  RESIDENTIAL: 0.10, AGRICULTURE: 0.05, RECREATION: 0.05,
}
DEFAULT_LU_CONST = 0.06
LU_TRIP_RATES = {
  RESIDENTIAL: 1.0, BUSINESS: 2.7, INDUSTRIAL: 2.0, SPECIAL: 1.2,
  TRANSPORT: 1.0, RECREATION: 1.4, AGRICULTURE: 0.2,
}
DEFAULT_TRIP_RATE = 1.0
DEFAULT_ACCESSIBILITY = 10
```

### 4.3 Origin-constrained gravity OD (rows = origins)

`acc_mx` is `nodes_to_nodes_mx`, zeros → NaN:

```
gravity_weights[i,j] = (1 / acc_mx[i,j]) * nodes_df.attractiveness[j]
# Preserve demand for isolated origins as intrazonal
empty_rows = (gravity_weights.sum(axis=1) == 0)
for node_id in empty_rows: gravity_weights.loc[node_id, node_id] = 1
# Row-normalize to probability
od_prob_mx = gravity_weights / gravity_weights.sum(axis=1)
# Integerize row by row preserving integer row sum (= demand)
od_int_mx = largest_remainder_round(od_prob_mx, demand = nodes_df.population)
```

- **Origin-constrained** (row sums equal integer origin population). Attractions are NOT constrained.
- Integerization: `_integerize_origin_constrained_od` rounds each row to integers preserving `sum(row) == int(demand)`, using `_round_probabilistic_row_to_int` (largest-remainder method).
- Isolated origins (zero row sum) get all demand as intrazonal (`gravity_weights[i,i] = 1`).

### 4.4 Road assignment (discrete, trip-by-trip)

```
H = preprocess(G):     normalize lanes, init intensity=0, compute capacity
graph_routing  = H.copy()
graph_congestion = H.copy()

for each (i, j, demand) in OD:
    if i == j or demand <= 0: continue
    trips = int(round(demand))
    for _ in range(trips):
        try: route = nx.dijkstra_path(graph_routing, i, j, weight=weight_key)
        except (NetworkXNoPath, NodeNotFound): break   # stop assigning this OD
        for (u, v) in consecutive pairs of route:
            k = argmin_{keys} graph_routing[u][v][k][weight_key]   # multi-edge selection
            graph_routing[u][v][k]["intensity"]   += 1
            graph_congestion[u][v][k]["intensity"] += 1
            if graph_routing[u][v][k]["intensity"] / max(capacity, 1e-9) > 1.0:
                graph_routing.remove_edge(u, v, key=k)            # capacity-clipped routing

for each edge: data["congestion_level"] = data["intensity"] / max(data["capacity"], 1e-9)
return graph_congestion
```

Notes (from docstring + code):
- Routing graph is mutated: oversaturated multiedges (specific `(u,v,key)` triples) are removed.
- Output graph keeps the full original edge set; saturation only affects routing choice.
- For parallel edges between `(u,v)`, the smallest-`weight_key` one is picked per step.
- Per-trip routing is `O(trips * dijkstra)` ⇒ **slow for large OD totals**; that's an inherent limitation, not a bug.

### 4.5 Capacity model

`capacity = LANE_CAPACITY * LANE_COEF[lanes] * lanes`, with:
`LANE_CAPACITY = 1000` and `LANE_COEF = {1:1.0, 2:0.95, 3:0.90, 4:0.86, 5:0.84, 6:0.82, 7:0.80, 8:0.78}`.

> ⚠ Docstring says "lanes 1..6" raise outside that range; the code's `LANE_COEF` dict actually defines 7, 8 too. **Skill should document the 1..6 contract from the docstring as authoritative**, since `_get_capacity_by_lanes` is `LANE_CAPACITY * LANE_COEF[lanes] * lanes` (will `KeyError` for any lanes > 8 or < 1).

---

## 5. External dependencies

From `pyproject.toml` of the branch:
- `iduedu == 0.4.1` (provides `get_drive_graph`, `get_walk_graph`, `get_intermodal_graph`, `get_adj_matrix_gdf_to_gdf`, `get_closest_nodes`, `graph_to_gdf`).
- `osmnx >= 2.0.0` (used in notebook for `ox.geocode_to_gdf`).
- `networkx >= 3.1,<4.0`.
- `pandera == 0.20.2` (schemas).
- `scikit-learn >= 1.4.2` (MinMaxScaler in `_calculate_attractiveness`).
- `loguru`, `tqdm`, `numpy>=2.0`, `pandas>=2.2.2`, `geopandas>=1.0.0`, `shapely>=2.0.6`.

Data source: `https://github.com/IDUclub/blocksnet-data/releases` — release artefacts are placed at `examples/data/<city>/` (e.g. `blocks.pickle`, `accessibility_matrix_drive.pickle`, …). The notebook reads `examples/data/blocks.pickle` (`./../data/blocks.pickle` from `examples/analysis/network/`).

`iduedu 0.4.1` verified exports (from wheel inspection):
```
iduedu.get_drive_graph, get_walk_graph, get_intermodal_graph,
        get_adj_matrix_gdf_to_gdf, get_closest_nodes, graph_to_gdf,
        get_all_public_transport_graph, get_single_public_transport_graph,
        join_pt_walk_graph, get_boundary
```

---

## 6. Tests

`tests/test_test.py` contains only `def test_test(): assert True`. **There are no unit tests covering `origin_destination` or `road_congestion` in this branch.** Any verification of skill behaviour must therefore be observational (re-running the notebook) or via direct property tests the skill author writes.

---

## 7. Pitfalls (compiled from source review)

1. **CRS hygiene**: every graph returned by `get_accessibility_graph` carries `graph.graph["crs"]` as an int EPSG; `validate_accessibility_graph` will raise `ValueError` if missing, not int, or invalid. The notebook reprojects internally via `osmnx`/`iduedu`, so the skill should not skip that step.
2. **`lanes` parsing edge cases**: `iduedu` can return `lanes` as a list (multiple OSM values) or a `;`-separated string. `_normalize_lanes` takes `min(list)` / first chunk — silently lossy. Skill should warn when this triggers.
3. **Origin-constrained gravity attractions are unbalanced**; row sums are integer, but column sums are not constrained. Document that this is by design.
4. **Integerization preserves only row sums, not OD totals** if individual origin demands round down; `od_mx.sum().sum()` may differ from `nodes_df.population.sum()` by O(N). The notebook doesn't enforce equality; the user must accept that drift.
5. **Intrazonal demand**: if a node has no valid gravity weights (e.g. all costs missing), all demand is assigned to the diagonal. This is documented in the docstring but easy to miss.
6. **Discrete assignment is `O(total_trips * dijkstra)`** — for `od_mx.sum().sum()` in the tens of thousands this is slow. Skill should expose `weight_key` and an opt-out.
7. **Oversaturation removal**: edges whose `intensity/capacity > 1.0` are removed from the **routing** graph (key-level), not from the **output** graph. So the output `graph_congestion` may have `intensity > capacity` and `congestion_level > 1.0` — that is the final load, not an error.
8. **`LANE_COEF` lookup is unguarded**: `_get_capacity_by_lanes` will `KeyError` on `lanes=0` or `lanes>8`. `_normalize_lanes` clamps `lanes<1` to `1`, but a hand-built graph with `lanes=9` will crash. Skill should pre-validate `lanes ∈ {1..6}` to match the docstring.
9. **Empty `count_*` columns**: `services_count` raises `ValueError` if no `count_*` columns (excluding `*_buildings`) exist. The notebook relies on the bundled `blocks.pickle` having these.
10. **`pandera==0.20.2` is pinned**; mismatched versions can break `Series[int]`/`GeoSeries` typing.
11. **Loguru/TQDM coupling**: `log_config.set_disable_tqdm(True)` reaches into `iduedu` config — turning off the notebook progress bars cleanly requires the official `log_config` API, not just `tqdm` globals.
12. **`LandUse` strings are case-insensitive** (parser lower-cases) but enum values are lowercase. `RESIDENTIAL` is OK; `"Residential"` is OK; `RES` is not.
13. **`get_adj_matrix_gdf_to_gdf` default dtype is `float16`**: very small values can quantize to 0; for OD weights the skill should consider `dtype=np.float32` to avoid precision loss on long trips.

---

## 8. Minimal runnable usage flow (for the skill)

```python
import pandas as pd
import osmnx as ox
from blocksnet.relations import get_accessibility_graph, accessibility_graph_to_gdfs
from blocksnet.analysis.services import services_count
from blocksnet.analysis.network import origin_destination_matrix, road_congestion
from iduedu import get_adj_matrix_gdf_to_gdf

# 1. Load + filter
blocks_gdf = pd.read_pickle("examples/data/saint_petersburg/blocks.pickle")
local_crs = blocks_gdf.crs
poly = ox.geocode_to_gdf("R1114252", by_osmid=True).to_crs(local_crs)
blocks_gdf = blocks_gdf[blocks_gdf.intersects(poly.union_all())]

# 2. Build graphs (drive graph must include "lanes" edge data)
graph_drive = get_accessibility_graph(blocks_gdf, "drive", additional_edgedata=["lanes"])
graph_walk  = get_accessibility_graph(blocks_gdf, "walk")

# 3. Adjacency matrices
nodes_gdf, _ = accessibility_graph_to_gdfs(graph_drive)
blocks_to_nodes = get_adj_matrix_gdf_to_gdf(blocks_gdf, nodes_gdf, graph_walk, weight="time_min", dtype="float32")
nodes_to_nodes  = get_adj_matrix_gdf_to_gdf(nodes_gdf,  nodes_gdf, graph_drive, weight="time_min", dtype="float32")

# 4. OD (origin-constrained gravity, integerized)
count_df = services_count(blocks_gdf)
od_mx = origin_destination_matrix(blocks_gdf, blocks_to_nodes, nodes_to_nodes, count_df)
assert (od_mx.sum(axis=1).astype("int64") >= 0).all()
assert list(od_mx.index) == list(od_mx.columns)

# 5. Road congestion (trip-by-trip discrete assignment)
graph_congestion = road_congestion(od_mx, graph_drive, weight_key="time_min")
_, edges_gdf = accessibility_graph_to_gdfs(graph_congestion)
assert {"intensity", "capacity", "congestion_level", "lanes"} <= set(edges_gdf.columns)
```

---

## 9. Recommended skill structure

A new agent skill `blocksnet-road-congestion` should expose (in this order):

1. **When to use** — trigger conditions:
   - User asks about road congestion, traffic load, link capacity utilization, or origin-destination flows on a blocksnet city model.
   - Has `blocks_gdf` (with `land_use`, `population`, `site_area`, `count_*`) and wants both OD and edge-level congestion.
2. **Prerequisites** — packages (`blocksnet[ipynb]`, `iduedu==0.4.1`, `osmnx>=2.0`), data (one of the `blocksnet-data` releases), CRS requirements (projected).
3. **Inputs contract** — list schemas from §2.
4. **Deterministic pipeline** — 12-step recipe from §3 (the notebook).
5. **Tunable parameters** — `accessibility` (default 10), `lu_consts`, `lu_trip_rates`, `weight_key` (default `"time_min"`), `LANE_CAPACITY`/`LANE_COEF` constants.
6. **Outputs** — `od_mx` (square int DataFrame) + `graph_congestion` (MultiDiGraph with `intensity`, `capacity`, `congestion_level` per edge) + `edges_gdf` for plotting.
7. **Pitfalls** — bullets from §7.
8. **Verification checklist** — see §10.
9. **References** — URLs (notebook + module paths).

---

## 10. Verification checklist (acceptance criteria for the skill)

Each item must be checkable in a single re-run of the reference notebook; failure ⇒ skill is wrong.

- [ ] `od_mx` is a square `pd.DataFrame` with `int64` dtype, index == columns, all node IDs ⊂ `graph_drive.nodes`.
- [ ] `od_mx.sum(axis=1)` matches (within rounding drift) the per-node integer population distributed from blocks.
- [ ] `intrazonal` flow exists only for origin nodes whose `nodes_to_nodes` row has no finite entries (else empty diagonal).
- [ ] Every edge in `graph_congestion` has `lanes≥1` (integer), `capacity>0`, `intensity≥0`, and `congestion_level = intensity / max(capacity, 1e-9)`.
- [ ] `lanes` edge attribute survives normalization (1, 2, 3, … — never a list or string).
- [ ] `graph_congestion` keeps the same edge set as `graph_drive` (no edges added/removed).
- [ ] `edges_gdf.plot('congestion_level', cmap='RdYlGn_r')` renders without error (visual smoke test).
- [ ] `services_count(blocks_gdf)` runs without `ValueError` (i.e. `count_*` columns present).
- [ ] `od_mx` row sum + `od_mx.sum().sum() == integerized total distributed population` (within ±N rounding).
- [ ] Total runtime note: discrete assignment is `O(sum(od_mx).sum())` Dijkstra calls; flag for the user if `od_mx.sum().sum() > 50_000`.
- [ ] No `KeyError` from `LANE_COEF` (i.e. all `lanes ∈ {1..6}` after normalization).
- [ ] `graph.graph["crs"]` is an int EPSG in both `graph_drive` and `graph_congestion`.

---

## 11. Exact source paths & URLs (for citation in the skill)

- Notebook: `https://github.com/aimclub/blocksnet/blob/feat/road_congestion/examples/analysis/network/od_and_rc.ipynb` (raw: `https://raw.githubusercontent.com/aimclub/blocksnet/feat/road_congestion/examples/analysis/network/od_and_rc.ipynb`).
- OD core: `blocksnet/analysis/network/origin_destination/core.py` (branch-local path: `blocksnet/analysis/network/origin_destination/core.py`).
- OD schemas: `blocksnet/analysis/network/origin_destination/schemas.py`.
- Road congestion: `blocksnet/analysis/network/road_congestion/core.py`.
- Graph validation: `blocksnet/relations/accessibility/graph/schemas.py` (`validate_accessibility_graph`, constants `CRS_KEY`, `WEIGHT_KEY="time_min"`, `X_KEY`, `Y_KEY`).
- Graph constructor: `blocksnet/relations/accessibility/graph/core.py` (`get_accessibility_graph`).
- Graph → gdfs: `blocksnet/relations/accessibility/graph/utils.py` (`accessibility_graph_to_gdfs`).
- Services count: `blocksnet/analysis/services/count/core.py` (`services_count`).
- Diversity: `blocksnet/analysis/diversity/shannon/core.py` (`shannon_diversity`, `SHANNON_DIVERSITY_COLUMN`).
- LandUse enum: `blocksnet/enums/land_use.py`.
- Pandera base schemas: `blocksnet/utils/validation/{gdf_schema.py,land_use_schema.py}`.
- pyproject deps: `pyproject.toml` line `iduedu==0.4.1`.
- Data releases: `https://github.com/IDUclub/blocksnet-data/releases`.
