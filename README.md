# blocksnet-agent

Tool-calling агент городской аналитики на основе библиотеки [blocksnet](https://github.com/aimclub/blocksnet).

Агент получает задачу на естественном языке, **рассуждает над ней до расчётов** (ANALYSIS PLAN с проверяемыми гипотезами и выбранными метриками), сам выбирает и вызывает инструменты анализа по предвычисленной локальной модели города, **разбирает результат после** (REFLECTION / HYPOTHESES / NUMERIC SELF-CHECK), проверяет гипотезы фактическим выводом инструментов и возвращает машиночитаемый структурированный ответ с уверенностью и ограничениями. Для генеративных вопросов («что и где строить») формирует измеренную гипотезу развития через TPE-оптимизатор и независимую сценарную проверку.

---

## Архитектура

```
Вопрос → AgentExecutor (ReAct, tool-calling)
        ↓                                          ↓
  краткие описания инструментов            ↻ цикл LLM ⇄ инструменты BlocksNet (max_iter)
        ↓                                          ↓
  ANALYSIS PLAN (рассуждение до расчётов)   intermediate_steps (tool/input/observation)
        ↓                                          ↓
  слой согласованности M1–M3 (заземление verdict'ов · самосогласованность с планом · план+саморефлексия) ·
  REFLECTION/RESULT из наблюдений · авто-скоринг CONFIDENCE → структурированный ответ
```

- **Движок** — `create_tool_calling_agent` + `AgentExecutor` (`return_intermediate_steps=True`): нативный tool-calling API без ручного парсинга Action/Observation; все шаги сохраняются для логирования и скоринга уверенности.
- **RAG по инструментам** — LLM видит короткие описания всех инструментов; полные контракты и подсказки доступны через `get_tool_help(name)`, поиск подходящих инструментов — через `find_tools(query)`. Заданных workflow-карточек нет: маршрут строится из плана, гипотез и доступных инструментов.
- **Структурированный вывод** (8 машиночитаемых секций, парсятся регулярками): `ANALYSIS PLAN`, `RESULT`, `REFLECTION`, `HYPOTHESES`, `NUMERIC SELF-CHECK`, `FOLLOW_UPS`, `CONFIDENCE`, `LIMITATIONS`.
- **Петля гипотез** generate → test → verify: `suggest_target_blocks` → `propose_zone_development` (TPE/Optuna) → `compute_scenario_provision` (независимый пересчёт обеспеченности before/after).
- **Кэш данных** (`tool_state: dict`) переживает вызовы `run()` — `blocks`, `acc_mx` и результаты `compute_*` не перечитываются повторно.

---

## Быстрый старт

```bash
git clone <repo-url>
cd blocksnet-agent
pip install -r requirements.txt
cp .env.example .env   # заполни ключи
```

```python
from blocksnet_agent import BlocksNetAgent, AgentResult

agent = BlocksNetAgent(model="openai/gpt-4o-mini")

result: AgentResult = agent.run(
    "Проанализируй транспортную доступность городских кварталов."
)

print(result["output"])       # структурированный ответ (ANALYSIS PLAN / RESULT / ...)
print(result["confidence"])   # 0.0–1.0, авто-скоринг по уликам
print(result["limitations"])  # список ограничений
print(result["run_dir"])      # каталог с CSV, картами и run_log
```

---

## Конфигурация

Создай `.env` в корне проекта:

```env
FP2MP_CHAT_URL=https://openrouter.ai/api/v1
FP2MP_API_KEY=sk-or-v1-...
FP2MP_MODEL=openai/gpt-4o-mini
```

| Переменная | Алиас | Описание | По умолчанию |
|---|---|---|---|
| `FP2MP_CHAT_URL` | `CHAT_URL` | URL OpenAI-совместимого API | — |
| `FP2MP_API_KEY` | `API_KEY` | Ключ авторизации | — |
| `FP2MP_MODEL` | `MODEL` | Имя модели | `gpt-4o-mini` |

Программно:

```python
from blocksnet_agent import BlocksNetAgent
from blocksnet_agent.config import Settings

agent = BlocksNetAgent(settings=Settings(chat_url="...", api_key="...", model="openai/gpt-4o"))
agent = BlocksNetAgent(model="openai/gpt-4o-mini", max_iterations=10)
```

---

## Структура проекта

```
blocksnet-agent/
├── blocksnet_agent/          # Python-пакет агента
│   ├── __init__.py           # BlocksNetAgent, AgentResult
│   ├── agent.py              # AgentExecutor + парсинг секций, слой согласованности M1–M3, скоринг confidence
│   ├── prompts.py            # system prompt (8 секций, правила планирования и заземления)
│   ├── config.py             # Settings + get_settings()
│   ├── llm.py                # фабрика ChatOpenAI (get_chat_model)
│   ├── runtime.py            # каталог запуска (run_*), record_file, run_log
│   └── tools/
│       ├── __init__.py       # make_tools() — фабрика 30 инструментов
│       ├── data.py           # загрузка модели, list_key_services, кэш (ensure_*)
│       ├── network.py        # доступность и связность
│       ├── provision.py      # обеспеченность сервисами (+ пресеты key/basic/advanced/comfort)
│       ├── services.py       # плотность, разнообразие, колокация, центральность
│       ├── indicators.py     # морфология FSI/GSI/MXI/OSR, граф смежности
│       ├── optimize.py       # TPE-оптимизация зон + compute_scenario_provision
│       ├── viz.py            # картограммы метрик (save_metric_map)
│       └── registry.py       # короткие/полные описания инструментов, find_tools/get_tool_help
├── data/
│   ├── blocks_with_services.gpkg   # кварталы + сервисы
│   ├── acc_mx.pickle               # предвычисленная матрица доступности
│   ├── service_type.json           # нормативы demand/accessibility сервисов
│   ├── archetypes.csv              # веса архетипов для TPE-оптимизатора
│   ├── platform/                   # GeoJSON сервисов
│   └── raw/                        # исходники для пересборки локальной модели
├── outputs/run_*/            # per-run: CSV, maps/*.png, run_log.{json,md}
├── requirements.txt
└── .env.example
```

---

## Формат вывода

```python
class AgentResult(TypedDict, total=False):
    input: str               # исходная задача
    output: str              # структурированный ответ (секции)
    log: list[BaseMessage]   # HumanMessage + AIMessage (с usage_metadata)
    confidence: float        # 0.0–1.0, авто-скоринг по числу успешных compute-вызовов,
                             #          наличию REFLECTION и верифицированных гипотез
    limitations: list[str]   # ограничения (в т.ч. выход за пределы локальной модели)
    sections: dict[str, str] # распарсенные секции по именам
    run_dir: str             # каталог запуска с артефактами
```

**Машиночитаемые секции** (`output` / `sections`):

| Секция | Назначение |
|---|---|
| `ANALYSIS PLAN` | Рассуждение **до** расчётов: вопрос → потребности → проверяемые гипотезы → метрики/инструменты с обоснованием |
| `RESULT` | Ключевые числа модели с единицами и интерпретацией |
| `REFLECTION` | Лучшие/худшие кварталы, дефициты, связь метрик — с числами и block_id |
| `HYPOTHESES` | claim / test / verdict; verdict обязан содержать число и block_id из вывода инструмента, иначе `unverified` |
| `NUMERIC SELF-CHECK` | Диапазоны, единицы, санити-проверка чисел |
| `FOLLOW_UPS` | Необязательные вопросы для следующего раунда анализа |
| `CONFIDENCE` | Самооценка агента 0.0–1.0 |
| `LIMITATIONS` | Что не учтено; явная пометка выхода за пределы `data/` |

Если агент не выдал `RESULT`/`REFLECTION`, пост-обработка восстанавливает их из наблюдений инструментов. До этого работает универсальный **слой согласованности** (`_refine_until_coherent`): незаземлённые verdict'ы, незакрытые потребности собственного `ANALYSIS PLAN` или отсутствие плана запускают повторный самоаудит-проход AgentExecutor (домен-нейтрально, до 2 проходов).

---

## Инструменты агента

30 инструментов в 7 семействах. Все результаты автоматически сохраняются в каталог запуска (`outputs/run_*`): CSV + картограммы (`maps/*.png`).

### Данные (`tools/data.py`)
`load_blocks` · `load_accessibility_matrix` · `list_cached_data` · `list_service_types` · `list_key_services` (нормативы demand/accessibility) · `get_block_info` · `get_analysis_results`

### Доступность (`tools/network.py`)
`compute_mean_accessibility` · `compute_median_accessibility` · `compute_max_accessibility` · `compute_connectivity` · `compute_land_use_accessibility` · `compute_area_accessibility`

### Обеспеченность (`tools/provision.py`)
`compute_service_provision` (конкретный сервис ИЛИ пресет `key/basic/advanced/comfort` — батч) · `compute_shared_provision`

### Сервисы и центральность (`tools/services.py`)
`compute_services_density` · `compute_services_count` · `compute_services_collocation` · `compute_shannon_diversity` · `compute_services_centrality` · `compute_population_centrality`

### Морфология (`tools/indicators.py`)
`compute_density_indicators` (FSI/GSI/MXI/OSR) · `compute_development_indicators` · `build_adjacency_graph`

### Оптимизация развития (`tools/optimize.py`)
`suggest_target_blocks` → `propose_zone_development` / `optimize_zone_services` (TPE/Optuna) → `compute_scenario_provision` (независимый before/after)

### Визуализация и справка
`render_metric_map` (`tools/viz.py`) · `find_tools` / `get_tool_help` (`tools/registry.py`)

---

## Справка по инструментам

Каждый инструмент документирован двухуровнево:

| Уровень | Как используется |
|---|---|
| Короткое описание | Показывается LLM в списке доступных инструментов для быстрого выбора |
| Полный docstring | Доступен через `get_tool_help(name)`: параметры, контракт входа/выхода, интерпретация, ограничения |

`find_tools(query)` выполняет keyword-поиск по реестру docstring-ов и возвращает подходящие инструменты. Это заменяет старые workflow-карточки: агент сам строит маршрут из своего `ANALYSIS PLAN`, гипотез и доступных инструментов.

---

## Примеры задач

```python
agent = BlocksNetAgent(model="openai/gpt-4o-mini")

# Диагностика доступности
agent.run("Какие районы наиболее и наименее связаны с остальным городом?")

# Обеспеченность набором сервисов (батч-пресет)
agent.run("Оцени обеспеченность населения базовым набором сервисов с порогом 15 минут.")

# Генеративная гипотеза развития (TPE + сценарная проверка)
agent.run("Где и что построить, чтобы повысить обеспеченность? Предложи и проверь сценарий.")

# Повторный запуск использует кэш данных; сброс — agent.reset()
agent.reset()
```

---

## Данные

| Файл | Описание |
|---|---|
| `data/blocks_with_services.gpkg` | Кварталы с сервисами, населением, землепользованием |
| `data/acc_mx.pickle` | Предвычисленная матрица доступности (время в пути, мин.) |
| `data/service_type.json` | Нормативы demand/accessibility сервисов |
| `data/archetypes.csv` | Веса архетипов для TPE-оптимизатора |
| `data/platform/` | GeoJSON сервисов |
| `data/raw/` | Исходные геоданные и GPKG для пересборки локальной модели |

> **Важно:** не пересчитывай матрицу доступности напрямую — используй готовый `acc_mx.pickle`.

---

## Зависимости

- [blocksnet](https://github.com/aimclub/blocksnet) — городской анализ + TPE-оптимизатор зон
- [LangChain](https://github.com/langchain-ai/langchain) (`langchain-classic` AgentExecutor, `langchain-openai`) — движок агента и подключение к LLM
- [Optuna](https://optuna.org/) — TPE для оптимизации зон
- [GeoPandas](https://geopandas.org/), [matplotlib](https://matplotlib.org/) — геоданные и картограммы
