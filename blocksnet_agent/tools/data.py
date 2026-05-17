from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
from langchain_core.tools import tool
from blocksnet.enums import LandUse


def _shape(value) -> str:
    if hasattr(value, "shape"):
        return str(value.shape)
    if hasattr(value, "number_of_nodes") and hasattr(value, "number_of_edges"):
        return f"граф ({value.number_of_nodes()} узлов, {value.number_of_edges()} ребер)"
    return type(value).__name__


def _service_columns(blocks: pd.DataFrame) -> list[str]:
    return sorted(c.replace("capacity_", "", 1) for c in blocks.columns if c.startswith("capacity_"))


def _parse_land_use(value):
    if isinstance(value, LandUse):
        return value
    if isinstance(value, str):
        key = value.split(".")[-1].upper()
        try:
            return LandUse[key]
        except KeyError:
            return value
    return value


def make_data_tools(ctx: dict) -> list:
    state = ctx["state"]
    data_dir = ctx["data_dir"]

    @tool
    def load_blocks() -> str:
        """Загружает GeoDataFrame кварталов с сервисами из data/blocks_with_services.gpkg."""
        try:
            blocks = gpd.read_file(data_dir / "blocks_with_services.gpkg")
            if "land_use" in blocks.columns:
                blocks["land_use"] = blocks["land_use"].apply(_parse_land_use)
            blocks["site_area"] = blocks.geometry.area
            state["blocks"] = blocks

            land_use_counts = blocks["land_use"].value_counts(dropna=False).to_dict() if "land_use" in blocks else {}
            services = _service_columns(blocks)
            lines = [
                f"Кварталы загружены: {blocks.shape[0]} строк, {blocks.shape[1]} столбцов.",
                f"CRS: {blocks.crs}",
                f"Землепользование: {{ {', '.join(f'{str(k)}: {v}' for k, v in land_use_counts.items())} }}",
            ]
            if "population" in blocks.columns:
                population = pd.to_numeric(blocks["population"], errors="coerce").fillna(0)
                lines.append(
                    f"Население - всего: {int(population.sum())}, среднее: {population.mean():.1f}, медиана: {population.median():.1f}"
                )
            lines.append(f"Типов сервисов: {len(services)}: {', '.join(services[:10])}{' ...' if len(services) > 10 else ''}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Ошибка при загрузке кварталов: {exc}"

    @tool
    def load_accessibility_matrix() -> str:
        """Загружает предвычисленную матрицу доступности из data/acc_mx.pickle."""
        try:
            acc_mx = pd.read_pickle(data_dir / "acc_mx.pickle")
            state["acc_mx"] = acc_mx
            values = acc_mx.to_numpy()
            flat = values[np.isfinite(values) & (values > 0)]
            return (
                f"Матрица доступности загружена: {acc_mx.shape[0]}x{acc_mx.shape[1]}, dtype={acc_mx.dtypes.iloc[0]}.\n"
                f"Время в пути (мин) - мин: {flat.min():.1f}, макс: {flat.max():.1f}, "
                f"среднее: {flat.mean():.1f}, медиана: {np.median(flat):.1f}."
            )
        except Exception as exc:
            return f"Ошибка при загрузке матрицы: {exc}"

    @tool
    def list_cached_data() -> str:
        """Возвращает список всех наборов данных в кэше агента с их размерами."""
        if not state:
            return "Кэш пуст. Загрузи данные с помощью load_blocks() и load_accessibility_matrix()."
        return "Данные в кэше:\n" + "\n".join(f"{key}: {_shape(value)}" for key, value in state.items())

    @tool
    def list_service_types() -> str:
        """Возвращает список типов сервисов из загруженных кварталов."""
        try:
            if "blocks" not in state:
                return "Ошибка: сначала вызови load_blocks()."
            services = _service_columns(state["blocks"])
            return f"Доступные типы сервисов ({len(services)} шт.):\n" + ", ".join(services)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def get_block_info(block_id: int) -> str:
        """Возвращает подробную информацию о квартале по индексу или колонке block_id."""
        try:
            if "blocks" not in state:
                return "Ошибка: сначала вызови load_blocks()."
            blocks = state["blocks"]
            row = blocks[blocks.index == block_id]
            if row.empty and "block_id" in blocks.columns:
                row = blocks[blocks["block_id"] == block_id]
            if row.empty:
                return f"Квартал с ID={block_id} не найден. Диапазон индекса: {blocks.index.min()}-{blocks.index.max()}."
            series = row.iloc[0].drop(labels=["geometry"], errors="ignore")
            lines = [f"Квартал ID={block_id}:"]
            for column, value in series.items():
                if pd.notna(value) and value != 0:
                    lines.append(f"  {column}: {value}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def get_analysis_results(result_key: str) -> str:
        """Извлекает из кэша краткую сводку ранее вычисленного результата."""
        try:
            if result_key not in state:
                return f"Ключ '{result_key}' не найден. Доступные: {list(state.keys())}"
            value = state[result_key]
            if isinstance(value, (pd.DataFrame, gpd.GeoDataFrame)):
                return (
                    f"Результат '{result_key}' ({value.shape}):\n"
                    f"Статистика:\n{value.describe().to_string()}\n\n"
                    f"Первые строки:\n{value.head(5).to_string()}"
                )
            if isinstance(value, pd.Series):
                return f"Результат '{result_key}' ({value.shape}):\n{value.describe().to_string()}\n\n{value.head(5).to_string()}"
            return f"'{result_key}': {str(value)[:500]}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [load_blocks, load_accessibility_matrix, list_cached_data, list_service_types, get_block_info, get_analysis_results]
