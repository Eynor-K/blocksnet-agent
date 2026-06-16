# План очистки и реорганизации blocksnet-agent

## Контекст

После нескольких итераций улучшений (RAG-инструменты, доменно-нейтральные инварианты,
удаление workflow-карточек) в репозитории накопились устаревшие файлы, дублирующиеся
данные (~84 MB мёртвых файлов) и несогласованная структура директорий.

Текущее состояние системы: confidence 0.78, заземление работает, честность статистики
восстановлена. Главный разрыв — отсутствие конкретного измеренного решения в финальном
ответе. Очистка создаёт фундамент для следующих итераций без технического долга.

---

## Шаг 1 — Код: устаревшие ссылки

**Файл:** `blocksnet_agent/agent.py:15`

**Проблема:** в модульном docstring описание M3 содержит «без содержательного ANALYSIS PLAN
со ссылкой на CARD id» — KB-карточки удалены три итерации назад, реальный `_plan_issue()`
проверяет только длину плана (>40 символов), без привязки к карточкам.

**Действие:** убрать фразу «со ссылкой на CARD id» из docstring, привести его в соответствие
с реальной реализацией.

**Риск:** нулевой — только docstring.

---

## Шаг 2 — Код: слияние M2 + critic (Приоритет 5 roadmap)

**Файл:** `blocksnet_agent/agent.py`, функции `_plan_consistency_issue` и `_consistency_critic`

**Проблема:** при каждом реентри вызываются 5 LLM-судей последовательно:
- M1: `_grounding_judge` — тест заявлен и выполнен?
- **M2: `_plan_consistency_issue` — план закрыт вызовами?**
- **T2.2: `_consistency_critic` — нет внутренних противоречий в RESULT↔REFLECTION↔HYPOTHESES?**
- Post: `_build_reflection`, `_build_hypothesis_verdicts`

M2 и T2.2 можно объединить в один промпт: «план выполнен AND нет противоречий между
секциями» — одним LLM-вызовом. Промпты разные по цели, но оба читают одни и те же секции
ответа и список вызовов.

**Действие:** создать `_plan_and_coherence_issue(plan, steps, output_text) -> str`,
которая одним вызовом судьи проверяет оба критерия. Удалить отдельные `_plan_consistency_issue`
и `_consistency_critic`. Обновить `_coherence_issues()`.

**Результат:** −1 LLM-вызов на каждый реентри → до −2 вызовов за прогон (бюджет реентри=2).
Примерно −20% стоимости и −20% латентности слоя согласованности.

**Риск:** средний — нужно аккуратно объединить два промпта без потери покрытия.

---

## Шаг 3 — data/: удаление мёртвых файлов (−84 MB)

### Удалить полностью

| Файл | Размер | Причина |
|---|---:|---|
| `data/genplanmos.f_zones.har` | 34 MB | HTTP Archive (браузерный захват), не читается кодом агента |
| `data/genplanmos.t_zones.har` | 13 MB | то же |
| `data/service_type_new.json` | 73 KB | дубль `service_type.json`, в коде не референсируется |

**Итого:** −47 MB

### Переместить в `data/raw/` (нужны только для пересборки модели)

Эти файлы используются только ноутбуками подготовки данных, **не** читаются кодом агента
(`blocks_with_services.gpkg` и `acc_mx.pickle` — единственные файлы, которые загружает агент).

| Файл | Размер |
|---|---:|
| `data/building.geojson` | 12 MB |
| `data/roads.geojson` | 12 MB |
| `data/functional_zones.geojson` | 6.2 MB |
| `data/terzones.geojson` | 3.0 MB |
| `data/water.geojson` | 1.4 MB |
| `data/railways.geojson` | 172 KB |
| `data/boundaries.geojson` | 28 KB |
| `data/blocks_cut.gpkg` | 936 KB |
| `data/agg_buildings_gdf.gpkg` | 1.4 MB |
| `data/buildings.gpkg` | 7.3 MB |
| `data/land_use_gdf.gpkg` | 1.4 MB |
| `data/boundaries.gpkg` | 108 KB |

### Остаётся в `data/` (читается агентом)

| Файл | Назначение |
|---|---|
| `blocks_with_services.gpkg` | основной GeoDataFrame кварталов |
| `acc_mx.pickle` | матрица доступности |
| `service_type.json` | нормативы сервисов |
| `archetypes.csv` | веса для TPE-оптимизатора |
| `platform/` | 57 GeoJSON сервисов |
| `raw/` | исходники для пересборки (новая папка) |

---

## Шаг 4 — examples/: разделение по назначению

### Удалить

| Файл | Причина |
|---|---|
| `examples/OptunaOptimizer.log` | устаревший лог оптимизатора |
| `examples/ЦМУТ_Сервисы - сервисы_ЦМУТ.csv` | внешний data-файл, не часть агента |
| `examples/outputs/` | промежуточные артефакты |

### Создать `notebooks/` — ноутбуки подготовки данных

Перенести из `examples/`:

```
notebooks/
  load.ipynb                  # загрузка данных
  model.ipynb                 # сборка модели blocksnet
  clean_blocks.ipynb          # предобработка кварталов
  buildings_pre.ipynb         # предобработка зданий
  load_platform.ipynb         # загрузка platform-данных
  processing_platform.ipynb   # обработка сервисов
  area_based_tpe.ipynb        # эксперименты с оптимизатором
```

### Остаётся в `examples/` — только прогоны агента

```
examples/
  experiment_1.ipynb          # «где разместить спортплощадки?»
  experiment_2.ipynb          # «что нужно в квартале 603?»
  experiment_3.ipynb          # (переименовать test.ipynb)
```

---

## Шаг 5 — docs/ + отчёты: актуализация

### Удалить устаревшие docs

| Файл | Причина |
|---|---|
| `docs/tools.md` | описывал архитектуру KB-карточек; источник истины теперь docstrings + `get_tool_help` |
| `docs/agent.md` | описывал workflow-пайплайн; устарел после перестройки на RAG |

Оставить: `docs/BlocksNetAgent — Архитектура и возможности.pdf`, `docs/README.md`.

### Создать `docs/reports/` — все MD-отчёты в одном месте

Перенести:

```
docs/reports/
  report_experiment_1_sports.md          # эксп.1 — итоговый (презентационный)
  report_experiment_2_block603.md        # эксп.2 — итоговый (презентационный)
  report_next_iterations.md              # дорожная карта
  # архивные (из examples/):
  report_experiment_1_original.md
  report_experiment_1_rerun.md
  report_experiment_2_original.md
  report_experiment_2_rerun.md
  report_rerun2_invariants.md
  improvement_plan.md
  implementation_notes.md
```

### Корень репозитория

Остаётся только `README.md`. Три файла `report_*.md` из корня — переместить в `docs/reports/`.

---

## Шаг 6 — Git: коммит + синхронизация worktree

1. Убрать `data/blocksnet_kb/` из staged-файлов worktree-ветки (KB удалена в предыдущих итерациях).
2. Применить все изменения шагов 1–5 к worktree.
3. Оформить коммит с описанием: «refactor: очистка репозитория — мёртвые данные, устаревшие docs, реструктуризация директорий, слияние M2+critic».
4. PR в main.

---

## Целевая структура

```
blocksnet-agent/
│
├── blocksnet_agent/           # пакет (структура не меняется)
│   ├── agent.py
│   ├── prompts.py
│   ├── runtime.py
│   ├── config.py
│   ├── llm.py
│   └── tools/
│       ├── data.py / network.py / provision.py
│       ├── services.py / indicators.py
│       ├── optimize.py / viz.py / registry.py
│       └── __init__.py
│
├── data/
│   ├── blocks_with_services.gpkg   ← агент читает
│   ├── acc_mx.pickle               ← агент читает
│   ├── service_type.json           ← агент читает
│   ├── archetypes.csv              ← TPE
│   ├── platform/                   ← 57 сервисов
│   └── raw/                        ← для пересборки (новая папка)
│
├── examples/                  # только прогоны агента
│   ├── experiment_1.ipynb
│   ├── experiment_2.ipynb
│   └── experiment_3.ipynb
│
├── notebooks/                 # подготовка данных (новая папка)
│   ├── load.ipynb / model.ipynb
│   ├── clean_blocks.ipynb / buildings_pre.ipynb
│   └── load_platform.ipynb / processing_platform.ipynb / area_based_tpe.ipynb
│
├── docs/
│   ├── reports/               # все MD-отчёты
│   ├── BlocksNetAgent.pdf
│   └── README.md
│
├── outputs/                   # авто-генерируемые прогоны (gitignore)
├── README.md
├── requirements.txt
└── .env.example
```

---

## Итог

| Метрика | До | После |
|---|---|---|
| Мёртвые файлы в data/ | ~84 MB | 0 |
| LLM-судьи/реентри | 5 | 4 |
| Устаревшие docs | 2 файла | 0 |
| Смешанные ноутбуки | 9 в examples/ | разделены по назначению |
| Отчёты (разбросаны) | в корне + examples/ | в docs/reports/ |
| Stale docstring | есть | нет |
