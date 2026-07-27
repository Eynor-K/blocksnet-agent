from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_DEMAND_PROXY = "population"


def block_demand_proxy(blocks: pd.DataFrame, service_type_or_set: Any = None) -> pd.Series:
    """Return a domain-neutral per-block demand proxy.

    The default proxy is positive population when available. This intentionally does not
    encode service-specific or land-use-specific rules; future callers can pass already
    computed demand columns through the same contract without changing ranking logic.
    """
    if "population" in blocks.columns:
        return pd.to_numeric(blocks["population"], errors="coerce").fillna(0.0)
    return pd.Series(1.0, index=blocks.index, dtype="float64")


def applicable_mask(blocks: pd.DataFrame, service_type_or_set: Any = None, min_demand: float = 0.0) -> pd.Series:
    """Blocks with applicable demand for demand-satisfaction rankings."""
    demand = block_demand_proxy(blocks, service_type_or_set)
    return (demand > float(min_demand)).reindex(blocks.index, fill_value=False)
