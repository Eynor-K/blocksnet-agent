from __future__ import annotations

import pandas as pd
from langchain_core.tools import tool
from blocksnet.analysis.provision import competitive_provision, provision_strong_total, provision_weak_total, shared_provision


def _require(state: dict, *keys: str) -> str | None:
    missing = [key for key in keys if key not in state]
    if missing:
        return f"Ошибка: отсутствуют данные {missing}. Сначала вызови load_blocks() и load_accessibility_matrix()."
    return None


def _service_df(state: dict, service_type: str) -> pd.DataFrame | str:
    err = _require(state, "blocks", "acc_mx")
    if err:
        return err
    cap_col = f"capacity_{service_type}"
    if cap_col not in state["blocks"].columns:
        return f"Ошибка: тип сервиса '{service_type}' не найден. Вызови list_service_types()."
    service_df = state["blocks"][["population", cap_col]].copy()
    service_df = service_df.rename(columns={cap_col: "capacity"}).fillna(0)
    service_df["capacity"] = service_df["capacity"].astype(int)
    service_df["population"] = service_df["population"].astype(int)
    return service_df


def _provision_column(df: pd.DataFrame) -> str:
    for col in ("provision_strong", "provision", "provision_weak"):
        if col in df.columns:
            return col
    numeric_cols = df.select_dtypes(include="number").columns
    return numeric_cols[-1]


def make_provision_tools(ctx: dict) -> list:
    state = ctx["state"]
    output_dir = ctx["output_dir"]

    @tool
    def compute_service_provision(service_type: str, accessibility_minutes: int = 15, max_depth: int = 1) -> str:
        """Вычисляет конкурентную обеспеченность населения конкретным типом сервиса."""
        try:
            service_df = _service_df(state, service_type)
            if isinstance(service_df, str):
                return service_df
            result = competitive_provision(service_df, state["acc_mx"], accessibility_minutes, max_depth=max_depth)
            blocks_prov = result[0] if isinstance(result, tuple) else result
            if isinstance(result, tuple):
                for index, item in enumerate(result[1:], start=1):
                    if isinstance(item, (pd.DataFrame, pd.Series)):
                        item.to_csv(output_dir / f"competitive_provision_{service_type}_links_{index}.csv")
            blocks_prov.to_csv(output_dir / f"competitive_provision_{service_type}.csv")
            state[f"competitive_provision_{service_type}"] = blocks_prov
            strong = provision_strong_total(blocks_prov)
            weak = provision_weak_total(blocks_prov)
            col = _provision_column(blocks_prov)
            values = pd.to_numeric(blocks_prov[col], errors="coerce").fillna(0)
            return (
                f"Обеспеченность сервисом '{service_type}' (порог {accessibility_minutes} мин):\n"
                f"Суммарная сильная обеспеченность: {strong:.3f}\n"
                f"Суммарная слабая обеспеченность: {weak:.3f}\n"
                f"Полная обеспеченность: {int((values >= 1).sum())} кварталов, "
                f"частичная: {int(((values > 0) & (values < 1)).sum())}, отсутствует: {int((values <= 0).sum())}."
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_shared_provision(service_type: str, accessibility_minutes: int = 15) -> str:
        """Вычисляет совместную обеспеченность населения сервисом в заданном пороге доступности."""
        try:
            service_df = _service_df(state, service_type)
            if isinstance(service_df, str):
                return service_df
            result = shared_provision(service_df, state["acc_mx"], accessibility_minutes)
            result_df = result[0] if isinstance(result, tuple) else result
            result_df.to_csv(output_dir / f"shared_provision_{service_type}.csv")
            state[f"shared_provision_{service_type}"] = result_df
            cols = [col for col in result_df.columns if "provision" in col.lower()]
            summary = result_df[cols].describe().to_string() if cols else result_df.describe().to_string()
            return f"Совместная обеспеченность '{service_type}' (порог {accessibility_minutes} мин):\n{summary}"
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [compute_service_provision, compute_shared_provision]
