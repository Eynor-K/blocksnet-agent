from __future__ import annotations

import numpy as np
from langchain_core.tools import tool
from blocksnet.analysis.indicators import calculate_density_indicators, calculate_development_indicators
from blocksnet.relations import generate_adjacency_graph


def _require(state: dict, *keys: str) -> str | None:
    missing = [key for key in keys if key not in state]
    if missing:
        return f"Ошибка: отсутствуют данные {missing}. Сначала вызови load_blocks()."
    return None


def make_indicators_tools(ctx: dict) -> list:
    state = ctx["state"]
    output_dir = ctx["output_dir"]

    @tool
    def compute_density_indicators() -> str:
        """Вычисляет индикаторы плотности городской застройки для каждого квартала."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            df = calculate_density_indicators(state["blocks"])
            state["density_indicators"] = df
            df.to_csv(output_dir / "density_indicators.csv")
            return f"Индикаторы плотности вычислены.\n{df.describe().to_string()}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_development_indicators() -> str:
        """Вычисляет индикаторы освоенности территории."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            df = calculate_development_indicators(state["blocks"])
            state["development_indicators"] = df
            df.to_csv(output_dir / "development_indicators.csv")
            return f"Индикаторы освоенности вычислены.\n{df.describe().to_string()}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def build_adjacency_graph(buffer_size: int = 0) -> str:
        """Строит граф пространственной смежности городских кварталов."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            graph = generate_adjacency_graph(state["blocks"], buffer_size=buffer_size)
            state["adjacency_graph"] = graph
            degrees = [degree for _, degree in graph.degree()]
            avg_degree = float(np.mean(degrees)) if degrees else 0.0
            return (
                f"Граф смежности построен: {graph.number_of_nodes()} узлов, {graph.number_of_edges()} ребер.\n"
                f"Средняя степень узла: {avg_degree:.2f}."
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [compute_density_indicators, compute_development_indicators, build_adjacency_graph]
