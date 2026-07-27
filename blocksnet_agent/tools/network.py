from __future__ import annotations

import pandas as pd
import numpy as np
from langchain_core.tools import tool
from blocksnet.analysis.network import (
    area_accessibility,
    calculate_connectivity,
    land_use_accessibility,
    max_accessibility,
    mean_accessibility,
    median_accessibility,
)
from blocksnet.enums import LandUse

from blocksnet_agent.runtime import record_file
from blocksnet_agent.tools.data import ensure_acc_mx, ensure_blocks
from blocksnet_agent.tools.viz import save_metric_map

# T2: метка, отличающая общегородской агрегат от поквартального значения.
_AGG_NOTE = (
    "\n[это агрегат по городу, НЕ значение отдельного квартала; "
    "поквартально — get_block_info(block_id) или get_metric_for_block(result_key, block_id)]"
)


def _numeric_series(result, name: str, col: str | None = None) -> pd.Series:
    if isinstance(result, pd.Series):
        return pd.to_numeric(result, errors="coerce").rename(name)
    if isinstance(result, pd.DataFrame):
        if col is None and name in result.columns:
            col = name
        if col is None:
            numeric_cols = result.select_dtypes(include="number").columns
            if len(numeric_cols) == 0:
                raise ValueError("result contains no numeric columns")
            col = numeric_cols[0]
        return pd.to_numeric(result[col], errors="coerce").rename(name)
    return pd.Series(result, name=name)


def _save(result, path) -> None:
    if isinstance(result, (pd.DataFrame, pd.Series)):
        result.to_csv(path)
    else:
        pd.Series(result).to_csv(path)
    record_file(path, "csv")


def _load_road_congestion_inputs(data_dir):
    """Load branch-specific OD/congestion inputs without synthesising spatial data."""
    import networkx as nx

    candidates = {
        "blocks_to_nodes": ("blocks_to_nodes.pickle", "blocks_to_nodes.pkl"),
        "nodes_to_nodes": ("nodes_to_nodes.pickle", "nodes_to_nodes.pkl"),
        "graph_drive": ("graph_drive.graphml", "drive.graphml"),
    }
    resolved = {}
    for key, names in candidates.items():
        path = next((data_dir / name for name in names if (data_dir / name).exists()), None)
        if path is None:
            raise FileNotFoundError(f"{key}: ожидается один из файлов {list(names)} в {data_dir}")
        resolved[key] = path

    blocks_to_nodes = pd.read_pickle(resolved["blocks_to_nodes"]).astype("float32")
    nodes_to_nodes = pd.read_pickle(resolved["nodes_to_nodes"]).astype("float32")
    graph_drive = nx.read_graphml(resolved["graph_drive"], node_type=int, force_multigraph=True)

    crs = graph_drive.graph.get("crs")
    if isinstance(crs, str):
        digits = "".join(char for char in crs if char.isdigit())
        if digits:
            graph_drive.graph["crs"] = int(digits)
    for _, data in graph_drive.nodes(data=True):
        for key in ("x", "y"):
            if key in data:
                data[key] = float(data[key])
    for _, _, _, data in graph_drive.edges(keys=True, data=True):
        if "time_min" in data:
            data["time_min"] = float(data["time_min"])

    return blocks_to_nodes, nodes_to_nodes, graph_drive


def _road_congestion_summary(edges_df: pd.DataFrame, total_trips: int) -> str:
    levels = pd.to_numeric(edges_df["congestion_level"], errors="coerce").dropna()
    intensities = pd.to_numeric(edges_df["intensity"], errors="coerce").fillna(0)
    loaded = int((intensities > 0).sum())
    saturated = int((levels > 1.0).sum())
    top = edges_df.assign(congestion_level=levels).nlargest(5, "congestion_level")
    return (
        f"OD и дорожная загруженность вычислены: поездок={total_trips}, "
        f"рёбер с потоком={loaded}, перегруженных рёбер (level>1)={saturated}.\n"
        f"congestion_level: мин={levels.min():.4f}, макс={levels.max():.4f}, "
        f"среднее={levels.mean():.4f}.\n"
        f"Топ-5 рёбер по загруженности:\n{top[['intensity', 'capacity', 'congestion_level']].to_string()}\n"
        "Метрика экспериментальная: требуется blocksnet из ветки feat/road_congestion; "
        "назначение выполняется по одной поездке (медленно на больших OD)."
    )


def _acc_summary(df: pd.DataFrame | pd.Series, col: str | None = "accessibility") -> str:
    if isinstance(df, pd.Series):
        series = pd.to_numeric(df, errors="coerce").dropna()
        label = df.name or "accessibility"
    else:
        if col is None or col not in df.columns:
            numeric_cols = df.select_dtypes(include="number").columns
            col = numeric_cols[0] if len(numeric_cols) else df.columns[0]
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        label = col
    top5 = series.nsmallest(5)
    bot5 = series.nlargest(5)
    return (
        f"Мин: {series.min():.2f}, макс: {series.max():.2f}, среднее: {series.mean():.2f}, медиана: {series.median():.2f}.\n"
        f"Топ-5 наиболее доступных (наименьшее время), {label}:\n{top5.to_string()}\n"
        f"Топ-5 наименее доступных (наибольшее время), {label}:\n{bot5.to_string()}"
        + _AGG_NOTE
    )


def make_network_tools(ctx: dict) -> list:
    state = ctx["state"]
    data_dir = ctx["data_dir"]
    output_dir = ctx["output_dir"]

    @tool
    def compute_mean_accessibility(out: bool = True) -> str:
        """Вычисляет среднее время доступности (мин) для каждого квартала по матрице доступности.

        Меньшее время — лучше; высокий максимум указывает на периферийность/разрывность сети.
        out=True — исходящая доступность (как из квартала доступны другие), out=False — входящая
        (как сам квартал доступен из других). Это доступность до ВСЕХ кварталов, не до конкретного сервиса.
        """
        try:
            df = mean_accessibility(ensure_acc_mx(state, data_dir), out=out)
            state["mean_accessibility"] = df
            _save(df, output_dir / "mean_accessibility.csv")
            save_metric_map(ensure_blocks(state, data_dir), df, "mean_accessibility", output_dir, "Средняя доступность")
            return f"Средняя доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_median_accessibility(out: bool = True) -> str:
        """Вычисляет медианное время доступности для каждого квартала."""
        try:
            df = median_accessibility(ensure_acc_mx(state, data_dir), out=out)
            state["median_accessibility"] = df
            _save(df, output_dir / "median_accessibility.csv")
            save_metric_map(ensure_blocks(state, data_dir), df, "median_accessibility", output_dir, "Медианная доступность")
            return f"Медианная доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_max_accessibility(out: bool = True) -> str:
        """Вычисляет максимальное время доступности для каждого квартала."""
        try:
            df = max_accessibility(ensure_acc_mx(state, data_dir), out=out)
            state["max_accessibility"] = df
            _save(df, output_dir / "max_accessibility.csv")
            save_metric_map(ensure_blocks(state, data_dir), df, "max_accessibility", output_dir, "Максимальная доступность")
            return f"Максимальная доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_connectivity(accessibility_key: str = "mean_accessibility") -> str:
        """Вычисляет связность транспортной сети из сохранённого результата доступности (нормированная).

        Требует предварительно вычисленную доступность (mean/median/max); если её нет, mean считается
        автоматически. accessibility_key — какой результат доступности использовать.
        """
        try:
            if accessibility_key not in state:
                state[accessibility_key] = mean_accessibility(ensure_acc_mx(state, data_dir), out=True)
            result = calculate_connectivity(state[accessibility_key])
            state["connectivity"] = result
            _save(result, output_dir / "connectivity.csv")
            save_metric_map(ensure_blocks(state, data_dir), result, "connectivity", output_dir, "Связность")
            series = _numeric_series(result, "connectivity")
            return (
                f"Связность вычислена.\nМин: {series.min():.4f}, макс: {series.max():.4f}, среднее: {series.mean():.4f}.\n"
                f"Топ-5 наиболее связных кварталов:\n{series.nlargest(5).to_string()}"
                + _AGG_NOTE
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_land_use_accessibility(land_use: str, out: bool = True) -> str:
        """Вычисляет доступность (мин) до кварталов определённого типа землепользования.

        land_use из enum LandUse: RESIDENTIAL, BUSINESS, RECREATION, TRANSPORT, INDUSTRIAL, SPECIAL.
        Среднее/медиана — общая близость к зоне; худшие кварталы выявляют пространственные разрывы.
        """
        try:
            lu = LandUse[land_use.upper()]
            df = land_use_accessibility(ensure_acc_mx(state, data_dir), ensure_blocks(state, data_dir), land_use=lu, out=out)
            key = f"land_use_accessibility_{land_use.lower()}"
            state[key] = df
            _save(df, output_dir / f"{key}.csv")
            save_metric_map(ensure_blocks(state, data_dir), df, key, output_dir, f"Доступность до зон {land_use}")
            return f"Доступность до зон {land_use} вычислена.\n" + _acc_summary(df, col=None)
        except KeyError:
            return f"Неверный тип: '{land_use}'. Допустимые: {[item.name for item in LandUse]}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_area_accessibility(out: bool = True) -> str:
        """Вычисляет площадно-взвешенную доступность."""
        try:
            df = area_accessibility(ensure_acc_mx(state, data_dir), ensure_blocks(state, data_dir), out=out)
            state["area_accessibility"] = df
            _save(df, output_dir / "area_accessibility.csv")
            save_metric_map(ensure_blocks(state, data_dir), df, "area_accessibility", output_dir, "Площадно-взвешенная доступность")
            return f"Площадно-взвешенная доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_road_congestion(accessibility: float = 10.0, max_trips: int = 50000) -> str:
        """Строит OD-матрицу и рассчитывает загруженность рёбер дорожного графа.

        Экспериментальная метрика из blocksnet feat/road_congestion. Требует в data_dir:
        blocks_with_services.gpkg, blocks_to_nodes.pickle, nodes_to_nodes.pickle и
        graph_drive.graphml (альтернативы *.pkl и drive.graphml поддержаны). В графе нужны
        int EPSG в graph['crs'], x/y узлов, time_min и lanes рёбер; после нормализации lanes
        должны быть 1..8. Кварталы должны иметь population, land_use, site_area и count_*;
        capacity_* автоматически преобразуются в count_* как число объектов с capacity>0.

        accessibility — порог block→node в минутах (ближайший узел включается всегда).
        max_trips — предохранитель от O(trips × Dijkstra); расчёт не запускается, если OD больше.
        Результаты: state['origin_destination_matrix'], state['road_congestion_edges']; CSV
        origin_destination_matrix.csv и road_congestion_edges.csv. congestion_level>1 допустим
        и означает перегрузку. Не использовать main blocksnet: API есть только в feature-ветке.
        """
        try:
            from blocksnet.analysis.network import origin_destination_matrix, road_congestion
            from blocksnet.analysis.services import services_count
            from blocksnet.relations import accessibility_graph_to_gdfs

            blocks = ensure_blocks(state, data_dir).copy()
            if "site_area" not in blocks:
                blocks["site_area"] = blocks.geometry.area
            count_columns = [column for column in blocks.columns if column.startswith("count_")]
            if not count_columns:
                capacity_columns = [column for column in blocks.columns if column.startswith("capacity_")]
                for column in capacity_columns:
                    blocks[f"count_{column.removeprefix('capacity_')}"] = (
                        pd.to_numeric(blocks[column], errors="coerce").fillna(0) > 0
                    ).astype(int)
            blocks_to_nodes, nodes_to_nodes, graph_drive = _load_road_congestion_inputs(data_dir)
            if set(blocks.index) != set(blocks_to_nodes.index):
                raise ValueError("индекс blocks должен совпадать с blocks_to_nodes")
            blocks = blocks.loc[blocks_to_nodes.index]
            node_ids = list(nodes_to_nodes.index)
            if list(nodes_to_nodes.columns) != node_ids or list(blocks_to_nodes.columns) != node_ids:
                raise ValueError("узлы blocks_to_nodes и квадратной nodes_to_nodes должны совпадать и иметь один порядок")
            graph_nodes = set(graph_drive.nodes)
            if not set(node_ids) <= graph_nodes:
                missing = sorted(set(node_ids) - graph_nodes)[:10]
                raise ValueError(f"OD-узлы отсутствуют в graph_drive: {missing}")
            invalid_lanes = []
            for u, v, key, data in graph_drive.edges(keys=True, data=True):
                raw = data.get("lanes", 1)
                try:
                    if isinstance(raw, list):
                        raw = min(raw) if raw else 1
                    if isinstance(raw, str):
                        raw = raw.replace("|", ";").replace(",", ";").split(";")[0]
                    lanes = int(float(raw))
                except (TypeError, ValueError):
                    lanes = 1
                if lanes < 1 or lanes > 8:
                    invalid_lanes.append((u, v, key, lanes))
            if invalid_lanes:
                raise ValueError(f"lanes вне поддерживаемого диапазона 1..8: {invalid_lanes[:5]}")

            count_df = services_count(blocks)
            od_mx = origin_destination_matrix(
                blocks,
                blocks_to_nodes,
                nodes_to_nodes,
                count_df,
                accessibility=float(accessibility),
            )
            total_trips = int(np.asarray(od_mx).sum())
            if total_trips > int(max_trips):
                raise ValueError(
                    f"OD содержит {total_trips} поездок > max_trips={max_trips}; "
                    "уменьши территорию или явно увеличь лимит"
                )
            graph_congestion = road_congestion(od_mx, graph_drive, weight_key="time_min")
            _, edges = accessibility_graph_to_gdfs(graph_congestion)
            state["origin_destination_matrix"] = od_mx
            state["road_congestion_edges"] = edges
            _save(od_mx, output_dir / "origin_destination_matrix.csv")
            _save(edges.drop(columns="geometry", errors="ignore"), output_dir / "road_congestion_edges.csv")
            return _road_congestion_summary(edges, total_trips)
        except ImportError as exc:
            return (
                "Ошибка: road congestion недоступен в установленной blocksnet. "
                "Установи aimclub/blocksnet из ветки feat/road_congestion и iduedu==0.4.1. "
                f"Детали: {exc}"
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [
        compute_mean_accessibility,
        compute_median_accessibility,
        compute_max_accessibility,
        compute_connectivity,
        compute_land_use_accessibility,
        compute_area_accessibility,
        compute_road_congestion,
    ]
