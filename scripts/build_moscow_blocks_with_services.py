"""Build the BlocksNet Moscow blocks_with_services input deterministically."""
from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "moscow" / "data"
BLOCKS_PATH = DATA / "blocks_gdf.parquet"
ZONES_PATH = DATA / "t_zones.gpkg"
BUILDINGS_PATH = DATA / "building_population_2022.gpkg"
SERVICES_PATH = DATA / "services_gdf.parquet"
OUTPUT_PATH = DATA / "blocks_with_services.gpkg"
TEMP_PATH = DATA / "blocks_with_services.tmp.gpkg"

VALID_LANDUSES = {
    "RESIDENTIAL",
    "BUSINESS",
    "RECREATION",
    "INDUSTRIAL",
    "TRANSPORT",
    "SPECIAL",
    "AGRICULTURE",
    "UNCLASSIFIED",
}


def normalized_landuse(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    value = str(value).split(".")[-1].strip().upper()
    return value if value in VALID_LANDUSES else None


def attach_pzz_landuse(blocks: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fill missing source classes from the PZZ polygon with largest overlap."""
    blocks = blocks.copy()
    blocks["land_use"] = blocks["land_use"].map(normalized_landuse)
    missing = blocks[blocks["land_use"].isna()].copy()
    if missing.empty:
        return blocks

    zones = gpd.read_file(ZONES_PATH)[["landuse", "geometry"]].to_crs(blocks.crs)
    zones["landuse"] = zones["landuse"].map(normalized_landuse).fillna("UNCLASSIFIED")
    candidates = gpd.sjoin(
        missing[["geometry"]].reset_index(names="block_id"),
        zones,
        how="inner",
        predicate="intersects",
    )
    if not candidates.empty:
        zone_geometries = zones.geometry
        candidates["overlap_area"] = candidates.apply(
            lambda row: row.geometry.intersection(zone_geometries.loc[row["index_right"]]).area,
            axis=1,
        )
        largest = candidates.loc[candidates.groupby("block_id")["overlap_area"].idxmax()]
        blocks.loc[largest["block_id"], "land_use"] = largest["landuse"].to_numpy()
    blocks["land_use"] = blocks["land_use"].fillna("UNCLASSIFIED")
    return blocks


def attach_population(blocks: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Assign each building population once, by its representative point."""
    buildings = gpd.read_file(BUILDINGS_PATH)[["Population", "geometry"]].to_crs(blocks.crs)
    buildings["geometry"] = buildings.geometry.representative_point()
    joined = gpd.sjoin(buildings, blocks[["geometry"]], how="left", predicate="within")
    # GeoPandas names a right-side index after the named index itself (`id`),
    # unlike the anonymous-index case where it is `index_right`.
    right_index = blocks.index.name or "index_right"
    if right_index not in joined:
        raise RuntimeError(f"Expected block key {right_index!r}, got {list(joined.columns)}")
    population = pd.to_numeric(joined["Population"], errors="coerce").fillna(0)
    by_block = population.groupby(joined[right_index]).sum()
    result = blocks.copy()
    result["population"] = result.index.to_series().map(by_block).fillna(0).round().astype("int64")
    return result


def service_slug(value: object) -> str:
    slug = re.sub(r"\s+", "_", str(value).strip().lower())
    slug = re.sub(r"[^a-z0-9_]+", "", slug)
    if not slug:
        raise ValueError(f"Invalid service type: {value!r}")
    return slug


def attach_service_capacity(blocks: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Aggregate source capacity by pre-attributed block and service type.

    ``services_gdf.parquet`` is the authoritative Moscow POI table: every row
    has ``block_id``, canonical ``service_type`` and deterministic ``capacity``.
    Capacity is summed, never inferred from POI count.
    """
    services = gpd.read_parquet(SERVICES_PATH)
    required = {"block_id", "service_type", "capacity"}
    missing = required - set(services.columns)
    if missing:
        raise ValueError(f"services_gdf.parquet lacks required columns: {sorted(missing)}")
    if not services["block_id"].isin(blocks.index).all():
        raise ValueError("services_gdf.parquet contains service rows outside blocks_gdf.parquet")
    capacity = pd.to_numeric(services["capacity"], errors="coerce")
    if capacity.isna().any() or (capacity < 0).any():
        raise ValueError("services_gdf.parquet has invalid capacity values")
    services = services.copy()
    services["service_slug"] = services["service_type"].map(service_slug)
    counts = pd.crosstab(services["block_id"], services["service_slug"])
    capacities = services.assign(capacity=capacity).pivot_table(
        index="block_id", columns="service_slug", values="capacity", aggfunc="sum", fill_value=0
    )
    if not counts.columns.equals(capacities.columns):
        raise ValueError("service count and capacity types differ")
    result = blocks.copy()
    for slug in counts.columns:
        result[f"count_{slug}"] = result.index.to_series().map(counts[slug]).fillna(0).astype("int32")
        result[f"capacity_{slug}"] = result.index.to_series().map(capacities[slug]).fillna(0).astype("int64")
    return result


def main() -> None:
    blocks = gpd.read_parquet(BLOCKS_PATH)
    if blocks.index.name != "id" or not blocks.index.is_unique:
        raise ValueError("blocks_gdf.parquet must have a unique 'id' index")
    if blocks.geometry.is_empty.any() or (~blocks.geometry.is_valid).any():
        raise ValueError("blocks_gdf.parquet has invalid geometries")

    blocks = attach_pzz_landuse(blocks)
    blocks = attach_population(blocks)
    blocks = attach_service_capacity(blocks)
    blocks["site_area"] = blocks.geometry.area

    if TEMP_PATH.exists():
        TEMP_PATH.unlink()
    blocks.to_file(TEMP_PATH, layer="blocks", driver="GPKG")
    check = gpd.read_file(TEMP_PATH)
    count_columns = [column for column in check if column.startswith("count_")]
    assert len(check) == len(blocks)
    assert {"geometry", "land_use", "population", "site_area"}.issubset(check.columns)
    assert check["land_use"].notna().all()
    assert check["population"].notna().all() and (check["population"] >= 0).all()
    assert len(count_columns) > 0 and (check[count_columns] >= 0).all().all()
    TEMP_PATH.replace(OUTPUT_PATH)

    print(f"output={OUTPUT_PATH}")
    print(f"rows={len(check)}")
    print(f"population={int(check['population'].sum())}")
    print(f"service_columns={len(count_columns)}")
    print("land_use=" + repr(check["land_use"].value_counts().sort_index().to_dict()))


if __name__ == "__main__":
    main()
