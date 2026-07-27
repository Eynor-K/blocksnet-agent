"""P0.4: регресс-тесты на устранение молчаливых фолбэков ``iloc[:, -1]``."""
from __future__ import annotations

import pandas as pd

from blocksnet_agent.tools.optimize import _numeric_metric
from blocksnet_agent.tools.data import _metric_series_for_blocks


def test_numeric_metric_prefers_named_provision_column() -> None:
    df = pd.DataFrame(
        {
            "population": [10, 20, 30],
            "shannon_diversity": [0.1, 0.2, 0.3],
            "provision": [0.0, 0.5, 0.9],
            "random_other": [99, 99, 99],
        }
    )
    series = _numeric_metric(df)
    assert series.name == "provision"
    assert list(series) == [0.0, 0.5, 0.9]


def test_numeric_metric_picks_single_numeric_column_with_name() -> None:
    # Одиночная не-preferred numeric-колонка должна быть выбрана с явным name.
    df = pd.DataFrame(
        {
            "population": [10, 20],
            "my_metric": [0.1, 0.2],
        },
        index=[1, 2],
    )
    # ``population`` тоже numeric — значит, не «ровно одна numeric» случай.
    # Используем только my_metric:
    df = pd.DataFrame({"my_metric": [0.1, 0.2]}, index=[1, 2])
    series = _numeric_metric(df)
    assert series.name == "my_metric"
    assert list(series) == [0.1, 0.2]


def test_numeric_metric_returns_empty_for_ambiguous_multi_numeric() -> None:
    """P0.4: несколько numeric-колонок без preferred → пустая серия, НЕ ``iloc[:, -1]``."""
    df = pd.DataFrame(
        {
            "alpha": [0.1, 0.2],
            "beta": [0.7, 0.8],
            "gamma": [0.3, 0.4],
        }
    )
    series = _numeric_metric(df)
    # Раньше здесь возвращался ``gamma`` (последний столбец) молча —
    # и отсюда в гипотезах всплывали «шумовые» 0.13. Теперь — пустая серия.
    assert series.empty


def test_metric_series_for_blocks_returns_none_for_ambiguous() -> None:
    # ``services_centrality`` есть в preferred-листе, поэтому он матчится первым;
    # используем две «посторонние» numeric-колонки, которых нет в preferred.
    df = pd.DataFrame(
        {
            "alpha": [0.1, 0.2],
            "beta": [0.7, 0.8],
        }
    )
    assert _metric_series_for_blocks(df) is None


def test_metric_series_for_blocks_picks_preferred_column() -> None:
    df = pd.DataFrame(
        {
            "services_centrality": [0.1, 0.2],
            "provision_strong": [0.7, 0.8],
        }
    )
    series = _metric_series_for_blocks(df)
    assert series is not None
    assert series.name == "provision_strong"
    assert list(series) == [0.7, 0.8]


def test_metric_series_for_blocks_handles_series() -> None:
    series = pd.Series([0.1, 0.2, 0.3])
    result = _metric_series_for_blocks(series)
    assert result is not None
    assert list(result) == [0.1, 0.2, 0.3]
