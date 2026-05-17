from __future__ import annotations

import pandas as pd
from langchain_core.tools import tool
from blocksnet.analysis.centrality import population_centrality, services_centrality
from blocksnet.analysis.diversity import shannon_diversity
from blocksnet.analysis.services import services_collocation, services_count, services_density


def _require(state: dict, *keys: str) -> str | None:
    missing = [key for key in keys if key not in state]
    if not missing:
        return None
    loaders = {"blocks": "load_blocks()", "acc_mx": "load_accessibility_matrix()", "adjacency_graph": "build_adjacency_graph()"}
    return f"Ошибка: отсутствуют данные {missing}. Сначала вызови: {', '.join(loaders.get(key, key) for key in missing)}."


def _save(result, path) -> None:
    if isinstance(result, (pd.DataFrame, pd.Series)):
        result.to_csv(path)
    else:
        pd.Series(result).to_csv(path)


def _series(result, name: str, col: str | None = None) -> pd.Series:
    if isinstance(result, pd.Series):
        return pd.to_numeric(result, errors="coerce").rename(name)
    if isinstance(result, pd.DataFrame):
        if col is None and name in result.columns:
            col = name
        if col is None:
            numeric_cols = result.select_dtypes(include="number").columns
            if len(numeric_cols) == 0:
                raise ValueError("result contains no numeric columns")
            col = numeric_cols[-1]
        return pd.to_numeric(result[col], errors="coerce").rename(name)
    return pd.Series(result, name=name)


def _summary(result, key: str, filename: str, output_dir, top_label: str = "Топ значений", col: str | None = None) -> str:
    path = output_dir / filename
    _save(result, path)
    if isinstance(result, pd.DataFrame) and col is None:
        numeric_cols = result.select_dtypes(include="number").columns
        if len(numeric_cols) == 0:
            return f"{key}: размер {result.shape}. Сохранено: {path}"
    values = _series(result, key, col=col).dropna()
    return (
        f"{key}: мин: {values.min():.4f}, макс: {values.max():.4f}, среднее: {values.mean():.4f}.\n"
        f"{top_label}:\n{values.nlargest(10).to_string()}\nСохранено: {path}"
    )


def make_services_tools(ctx: dict) -> list:
    state = ctx["state"]
    output_dir = ctx["output_dir"]

    @tool
    def compute_services_density() -> str:
        """Вычисляет плотность сервисов для каждого квартала."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            df = services_density(state["blocks"])
            state["services_density"] = df
            _save(df, output_dir / "services_density.csv")
            return f"Плотность сервисов вычислена.\n{df.describe().to_string()}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_services_count() -> str:
        """Подсчитывает количество объектов каждого типа сервиса по кварталам."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            df = services_count(state["blocks"])
            state["services_count"] = df
            _save(df, output_dir / "services_count.csv")
            return f"Количество сервисов вычислено.\n{df.describe().to_string()}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_services_collocation() -> str:
        """Анализирует совместное расположение типов сервисов в кварталах."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            df = services_collocation(state["blocks"])
            state["services_collocation"] = df
            _save(df, output_dir / "services_collocation.csv")
            return f"Колокация сервисов вычислена.\n{df.to_string()[:1000]}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_shannon_diversity() -> str:
        """Вычисляет индекс разнообразия Шеннона для распределения сервисов по кварталам."""
        try:
            err = _require(state, "blocks")
            if err:
                return err
            result = shannon_diversity(state["blocks"])
            state["shannon_diversity"] = result
            return _summary(result, "shannon_diversity", "shannon_diversity.csv", output_dir, "Топ-10 кварталов по разнообразию", col="shannon_diversity")
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_services_centrality() -> str:
        """Вычисляет составной индекс центральности кварталов на основе сервисов и доступности."""
        try:
            err = _require(state, "blocks", "acc_mx")
            if err:
                return err
            result = services_centrality(state["acc_mx"], state["blocks"])
            state["services_centrality"] = result
            return _summary(result, "services_centrality", "services_centrality.csv", output_dir, "Топ-10 наиболее центральных кварталов")
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_population_centrality() -> str:
        """Вычисляет центральность кварталов на основе населения и графа смежности."""
        try:
            err = _require(state, "blocks", "adjacency_graph")
            if err:
                return err
            result = population_centrality(state["blocks"], state["adjacency_graph"])
            state["population_centrality"] = result
            return _summary(result, "population_centrality", "population_centrality.csv", output_dir, "Топ-10", col="population_centrality")
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [
        compute_services_density,
        compute_services_count,
        compute_services_collocation,
        compute_shannon_diversity,
        compute_services_centrality,
        compute_population_centrality,
    ]
