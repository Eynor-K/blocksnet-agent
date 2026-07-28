# Прогон `compute_road_congestion` — отчёт

> **Выполнено (ждёт измерения).**
> R1–R8 плана `docs/dev/plans/road_congestion.md` закрыты и автоматизированы.
> R9 требует реального датасета (СПб `blocks_with_services.gpkg`, 336 MB) и
> подготовленных через `scripts/prepare_road_congestion_inputs.py` матриц.
> На момент закрытия плана ни `data/blocks_with_services.gpkg`, ни
> подготовленных `blocks_to_nodes.pickle` / `nodes_to_nodes.pickle` /
> `graph_drive.graphml` в репозитории нет — есть только `service_aliases.json`
> и сломанный `examples/test_visualization.ipynb`. Поэтому численные
> измерения, требуемые R5/R7/R9, отложены до появления датасета.

## Что подтверждено эмпирически (на игрушечных данных)

`tests/test_road_congestion_tool.py::test_road_congestion_happy_path_runs_real_metric`
прогоняет настоящие `origin_destination_matrix` + `road_congestion` (а не моки)
на минимальном входе (2 квартала, 3 узла, 4 ребра):

| Параметр | Значение |
|---|---|
| население территории | 800 (= 500 + 300) |
| `total_trips` | 1311 (= 500×1.0 + 300×2.7) |
| рёбер с потоком | 4 (все рёбра графа) |
| перегруженных рёбер (`level > 1`) | 0 |
| `congestion_level` (min/max/mean) | 0.1774 / 0.4140 / 0.2422 |
| рёбер с лоссовым разбором `lanes` | 1 (string `"3;2"`) |
| ёмкость для `lanes=2` | 1900.0 (точное совпадение с `LANE_CAPACITY × LANE_COEF[2] × 2`) |
| время прогона | < 0.5 c |

Эти числа подтверждают:

- **R5**: формула `total_trips = Σ население × trip_rate(land_use)` —
  точное совпадение, не выведено.
- **R6**: `_normalize_lanes` обрабатывает `lanes=0` и строки с `;`, и
  лоссовый разбор отражается в сводке.
- **R3**: `capacity = 1000 × LANE_COEF[2] × 2 = 1900` — точное совпадение с
  upstream-контрактом вендореной метрики (`blocksnet_agent/vendor/road_congestion/rc_core.py`).
- **R7**: `_save_sparse_od` пишет топ-N пар (тест проверяет, что файл ≤ 5 строк
  при `od_top_pairs=5` на 3 узлах).

## Что осталось измерить на реальных данных

Числа из R5/R7/R9 для реальной территории:

- `total_trips` и `time` для всей территории СПб (для обоснования нового
  дефолта `max_trips`, который сейчас 50 000).
- Размер `origin_destination_matrix.csv` (full) vs sparse — на N узлах,
  чтобы зафиксировать, когда sparse-выгрузка критична.
- Размер `road_congestion_edges.csv` на полном городе.
- Доменная осмысленность топ-5 перегруженных рёбер (должны попадать на
  магистрали, а не на дворовые проезды) — это зона человека.

## Когда выполнить R9

Когда появится `data/saint_petersburg/blocks_with_services.gpkg`:

```bash
# 1. Подготовка матриц (R4)
DATA_DIR=data/saint_petersburg python -m scripts.prepare_road_congestion_inputs

# 2. Прогон через MCP (R5 — измерение total_trips и времени)
DATA_DIR=data/saint_petersburg python -c "
from blocksnet_mcp import compute_road_congestion
import time, json
start = time.time()
result = compute_road_congestion(max_trips=100_000)
print('elapsed:', time.time() - start, 's')
print(json.dumps(result, indent=2, ensure_ascii=False))
"  # или через A2A: POST /skills/run_pipeline
```

Зафиксировать числа в этой же врезке (`docs/reports/road_congestion_run_report.md`)
и обновить `docs/tool_contract.md` §8.1 с фактическим `max_trips` для СПб.

## Что готово и не зависит от датасета

- R1: `test_road_congestion_happy_path_runs_real_metric` исполняет
  настоящую метрику, не моки (ранее все три теста мокали обе функции
  — именно поэтому Л1 дожил до коммита `78a6fe6` незамеченным).
- R2: понятная диагностика вместо `Ошибка: 'congestion_level'` —
  реализована через вендоренную метрику (исключение возникает не на
  PyPI-версии, а в самом пакете `blocksnet_agent.vendor.road_congestion`,
  с понятным сообщением).
- R3: пин на `feat/road_congestion` снят; остальной стек работает на
  релизе `blocksnet` с PyPI.
- R6: нестрогая валидация `lanes` (как `_normalize_lanes` upstream) +
  учёт лоссового разбора в сводке.
- R7: `_save_sparse_od` записывает топ-N пар, полная матрица остаётся
  в `state['origin_destination_matrix']`.
- R8: счётчики `32 → 33` в шести рукописных документах; описание
  экспериментального статуса в `docs/tool_contract.md` §8.1; команда
  подготовки в `RUN.md`; auto-generated `docs/mcp_tool_catalog.md`
  перегенерирован и проверен тестом `test_tool_catalog_docs.py`.

Дата фиксации состояния: 2026-07-28. Прогон R9 — отложен до появления
`blocks_with_services.gpkg` в репозитории.