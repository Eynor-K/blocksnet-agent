# blocksnet-agent

ReAct-агент для городского планирования на основе библиотеки [blocksnet](https://github.com/aimclub/blocksnet).

Агент получает задачу на естественном языке, самостоятельно выбирает и вызывает инструменты анализа, сохраняет результаты в CSV-файлы и возвращает структурированный ответ.

---

## Быстрый старт

```bash
# 1. Клонируй репозиторий
git clone <repo-url>
cd blocksnet-agent

# 2. Установи зависимости
pip install -r requirements.txt

# 3. Создай .env из шаблона и заполни ключи
cp .env.example .env
```

```python
from blocksnet_agent import BlocksNetAgent, AgentResult

agent = BlocksNetAgent()

result: AgentResult = agent.run(
    "Проанализируй транспортную доступность городских кварталов."
)

print(result["input"])   # исходная задача
print(result["output"])  # финальный ответ агента
for msg in result["log"]:
    print(type(msg).__name__, ":", str(msg.content)[:200])
```

---

## Установка

**Требования:** Python 3.11+

```bash
pip install -r requirements.txt
```

`requirements.txt`:
```
langgraph>=1.1.0
langchain-openai>=1.2.0
langchain-core>=1.3.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
geopandas>=0.14.0
pandas>=2.0.0
numpy>=1.24.0
blocksnet>=1.0.0a9
```

---

## Конфигурация

Создай файл `.env` в корне проекта:

```env
# OpenAI-совместимый API (OpenRouter, OpenAI, LM Studio и др.)
FP2MP_CHAT_URL=https://openrouter.ai/api/v1
FP2MP_API_KEY=sk-or-v1-...

# Имя модели (для OpenRouter используй формат provider/model)
FP2MP_MODEL=openai/gpt-4o
```

Поддерживаемые переменные:

| Переменная | Алиас | Описание | По умолчанию |
|---|---|---|---|
| `FP2MP_CHAT_URL` | `CHAT_URL` | URL API-эндпоинта | — |
| `FP2MP_API_KEY` | `API_KEY` | Ключ авторизации | — |
| `FP2MP_MODEL` | `MODEL` | Имя модели | `gpt-4o-mini` |

Настройки также можно передать программно:

```python
from blocksnet_agent import BlocksNetAgent
from blocksnet_agent.config import Settings

settings = Settings(
    chat_url="https://openrouter.ai/api/v1",
    api_key="sk-or-v1-...",
    model="openai/gpt-4o",
)
agent = BlocksNetAgent(settings=settings)

# или только модель
agent = BlocksNetAgent(model="openai/gpt-4o-mini")
```

---

## Структура проекта

```
blocksnet-agent/
├── blocksnet_agent/          # Python-пакет агента
│   ├── __init__.py           # BlocksNetAgent, AgentResult
│   ├── agent.py              # класс агента
│   ├── config.py             # Settings (pydantic-settings)
│   ├── prompts.py            # системный промпт
│   └── tools/                # инструменты blocksnet
│       ├── __init__.py       # make_tools() — фабрика
│       ├── data.py           # загрузка данных
│       ├── network.py        # анализ доступности
│       ├── provision.py      # обеспеченность сервисами
│       ├── services.py       # сервисы и централность
│       └── indicators.py     # индикаторы и граф смежности
├── data/                     # геопространственные данные
│   ├── blocks_with_services.gpkg   # кварталы + сервисы
│   ├── acc_mx.pickle               # матрица доступности
│   └── platform/                   # 68 GeoJSON файлов сервисов
├── examples/
│   └── demo.ipynb            # демонстрационный ноутбук
├── outputs/                  # CSV-результаты анализа
├── requirements.txt
└── .env.example
```

---

## Формат вывода

```python
class AgentResult(TypedDict):
    input: str               # исходная задача
    output: str              # финальный ответ агента
    log: list[BaseMessage]   # история: HumanMessage + AIMessage
```

```python
result = agent.run("Какие кварталы наименее доступны?")

result["input"]   # → "Какие кварталы наименее доступны?"
result["output"]  # → "Наименее доступными являются кварталы №..."
result["log"]     # → [HumanMessage(...), AIMessage(...), AIMessage(...)]

from langchain_core.messages import BaseMessage
assert all(isinstance(m, BaseMessage) for m in result["log"])
```

---

## Инструменты агента

Агент управляет 23 инструментами blocksnet, разбитыми по группам.

### Загрузка данных (`tools/data.py`)

| Инструмент | Описание |
|---|---|
| `load_blocks()` | Загружает кварталы из `blocks_with_services.gpkg` |
| `load_accessibility_matrix()` | Загружает матрицу доступности из `acc_mx.pickle` |
| `list_cached_data()` | Показывает, что уже загружено в кэш |
| `list_service_types()` | Перечисляет доступные типы сервисов |
| `get_block_info(block_id)` | Детальная информация о квартале по ID |
| `get_analysis_results(key)` | Сводка по ранее вычисленному результату |

### Сетевая доступность (`tools/network.py`)

| Инструмент | Описание |
|---|---|
| `compute_mean_accessibility(out)` | Среднее время в пути от/до каждого квартала |
| `compute_median_accessibility(out)` | Медианное время (устойчиво к выбросам) |
| `compute_max_accessibility(out)` | Максимальное время (наихудший сценарий) |
| `compute_connectivity(key)` | Связность сети (1 / время) |
| `compute_land_use_accessibility(land_use, out)` | Доступность до зон заданного типа |
| `compute_area_accessibility(out)` | Площадно-взвешенная доступность |

### Обеспеченность сервисами (`tools/provision.py`)

| Инструмент | Описание |
|---|---|
| `compute_service_provision(service, minutes, depth)` | Конкурентная обеспеченность населения сервисом |
| `compute_shared_provision(service, minutes)` | Совместная обеспеченность (доля населения с доступом) |

### Сервисы и централность (`tools/services.py`)

| Инструмент | Описание |
|---|---|
| `compute_services_density()` | Плотность сервисов (объектов на кв. км) |
| `compute_services_count()` | Количество объектов каждого типа сервиса |
| `compute_services_collocation()` | Попарная матрица совместного расположения сервисов |
| `compute_shannon_diversity()` | Индекс разнообразия Шеннона для сервисной среды |
| `compute_services_centrality()` | Составная централность по связности, плотности, разнообразию |
| `compute_population_centrality()` | Централность по численности населения и смежности |

### Индикаторы и граф (`tools/indicators.py`)

| Инструмент | Описание |
|---|---|
| `compute_density_indicators()` | FSI, GSI, MXI, L, OSR для каждого квартала |
| `compute_development_indicators()` | Индикаторы освоенности территории |
| `build_adjacency_graph(buffer_size)` | Граф пространственной смежности кварталов |

Все результаты автоматически сохраняются в папку `outputs/` в виде CSV.

---

## Примеры задач

```python
agent = BlocksNetAgent()

# Транспортная доступность
r1 = agent.run(
    "Проанализируй транспортную доступность городских кварталов. "
    "Какие районы наиболее и наименее связаны с остальным городом?"
)

# Обеспеченность сервисами
r2 = agent.run(
    "Оцени обеспеченность населения школами с порогом 15 минут. "
    "Назови кварталы с наибольшим дефицитом."
)

# Разнообразие сервисной среды
r3 = agent.run(
    "Вычисли индекс разнообразия Шеннона и централность кварталов. "
    "Какие районы имеют наиболее разнообразную сервисную среду?"
)

# Повторный запуск без перезагрузки данных (кэш сохраняется между run())
r4 = agent.run("Теперь добавь анализ плотности застройки (FSI, GSI).")

# Сброс кэша при необходимости
agent.reset()
```

---

## Данные

| Файл | Описание | Размер |
|---|---|---|
| `data/blocks_with_services.gpkg` | 3113 кварталов, 153 атрибута, 67 типов сервисов | ~2 МБ |
| `data/acc_mx.pickle` | Матрица доступности 3113×3113 (время в пути, мин.) | ~19 МБ |
| `data/building.gpkg` | Контуры зданий | ~31 МБ |
| `data/platform/*.geojson` | 68 файлов с расположением объектов сервисов | ~5 МБ |

> **Важно:** не вызывай `calculate_accessibility_matrix()` напрямую — пересчёт матрицы занимает несколько часов. Используй готовый `acc_mx.pickle`.

---

## Производительность

| Операция | Время |
|---|---|
| Загрузка кварталов | 2–5 с |
| Загрузка матрицы доступности | 1–3 с |
| Анализ доступности (mean/median/max) | 2–10 с |
| Индекс Шеннона | 1–3 с |
| Обеспеченность сервисом | 15–60 с |
| Централность сервисов | 5–15 с |
| Граф смежности | 20–60 с |
| Индикаторы плотности (FSI/GSI) | 1–5 с |

---

## Демонстрационный ноутбук

Открой `examples/demo.ipynb` в Jupyter для интерактивного запуска:

```bash
jupyter notebook examples/demo.ipynb
```

---

## Зависимости

- [blocksnet](https://github.com/aimclub/blocksnet) — библиотека городского анализа
- [LangGraph](https://github.com/langchain-ai/langgraph) — фреймворк ReAct-агента
- [LangChain OpenAI](https://github.com/langchain-ai/langchain) — подключение к LLM
- [GeoPandas](https://geopandas.org/) — работа с геоданными
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — конфигурация
