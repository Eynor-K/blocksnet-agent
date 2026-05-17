from __future__ import annotations

import pandas as pd
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


def _require(state: dict, *keys: str) -> str | None:
    missing = [key for key in keys if key not in state]
    if not missing:
        return None
    loaders = {"blocks": "load_blocks()", "acc_mx": "load_accessibility_matrix()", "adjacency_graph": "build_adjacency_graph()"}
    hints = ", ".join(loaders.get(key, key) for key in missing)
    return f"Ошибка: отсутствуют данные {missing}. Сначала вызови: {hints}."


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
    )


def make_network_tools(ctx: dict) -> list:
    state = ctx["state"]
    output_dir = ctx["output_dir"]

    @tool
    def compute_mean_accessibility(out: bool = True) -> str:
        """Вычисляет среднее время доступности для каждого квартала по матрице доступности."""
        try:
            err = _require(state, "acc_mx")
            if err:
                return err
            df = mean_accessibility(state["acc_mx"], out=out)
            state["mean_accessibility"] = df
            _save(df, output_dir / "mean_accessibility.csv")
            return f"Средняя доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_median_accessibility(out: bool = True) -> str:
        """Вычисляет медианное время доступности для каждого квартала."""
        try:
            err = _require(state, "acc_mx")
            if err:
                return err
            df = median_accessibility(state["acc_mx"], out=out)
            state["median_accessibility"] = df
            _save(df, output_dir / "median_accessibility.csv")
            return f"Медианная доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_max_accessibility(out: bool = True) -> str:
        """Вычисляет максимальное время доступности для каждого квартала."""
        try:
            err = _require(state, "acc_mx")
            if err:
                return err
            df = max_accessibility(state["acc_mx"], out=out)
            state["max_accessibility"] = df
            _save(df, output_dir / "max_accessibility.csv")
            return f"Максимальная доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_connectivity(accessibility_key: str = "mean_accessibility") -> str:
        """Вычисляет связность транспортной сети из сохраненного результата доступности."""
        try:
            if accessibility_key not in state:
                return f"Ошибка: '{accessibility_key}' не в кэше. Сначала вычисли доступность."
            result = calculate_connectivity(state[accessibility_key])
            state["connectivity"] = result
            _save(result, output_dir / "connectivity.csv")
            series = _numeric_series(result, "connectivity")
            return (
                f"Связность вычислена.\nМин: {series.min():.4f}, макс: {series.max():.4f}, среднее: {series.mean():.4f}.\n"
                f"Топ-5 наиболее связных кварталов:\n{series.nlargest(5).to_string()}"
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_land_use_accessibility(land_use: str, out: bool = True) -> str:
        """Вычисляет доступность до кварталов определенного типа землепользования."""
        try:
            err = _require(state, "blocks", "acc_mx")
            if err:
                return err
            lu = LandUse[land_use.upper()]
            df = land_use_accessibility(state["acc_mx"], state["blocks"], land_use=lu, out=out)
            key = f"land_use_accessibility_{land_use.lower()}"
            state[key] = df
            _save(df, output_dir / f"{key}.csv")
            return f"Доступность до зон {land_use} вычислена.\n" + _acc_summary(df, col=None)
        except KeyError:
            return f"Неверный тип: '{land_use}'. Допустимые: {[item.name for item in LandUse]}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_area_accessibility(out: bool = True) -> str:
        """Вычисляет площадно-взвешенную доступность."""
        try:
            err = _require(state, "blocks", "acc_mx")
            if err:
                return err
            df = area_accessibility(state["acc_mx"], state["blocks"], out=out)
            state["area_accessibility"] = df
            _save(df, output_dir / "area_accessibility.csv")
            return f"Площадно-взвешенная доступность (out={out}) вычислена.\n" + _acc_summary(df, col=None)
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [
        compute_mean_accessibility,
        compute_median_accessibility,
        compute_max_accessibility,
        compute_connectivity,
        compute_land_use_accessibility,
        compute_area_accessibility,
    ]
