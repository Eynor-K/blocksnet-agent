# Документация BlocksNetAgent

Tool-calling агент городской аналитики над библиотекой [blocksnet](https://github.com/aimclub/blocksnet): рассуждает над задачей до расчётов, считает индикаторы по локальной модели города, генерирует и измеряет гипотезы развития, возвращает структурированный машиночитаемый ответ.

## Содержание

| Документ | О чём |
|---|---|
| [../README.md](../README.md) | Установка, быстрый старт, архитектура, структура данных, инструменты и формат вывода |
| [reports/](reports/) | Итоговые и архивные отчеты по экспериментам и итерациям улучшений |
| [BlocksNetAgent — Архитектура и возможности.pdf](BlocksNetAgent%20—%20Архитектура%20и%20возможности.pdf) | Презентация архитектуры (слайды) |

## Быстрые ссылки

- Корневой [README.md](../README.md) — установка, быстрый старт, конфигурация.
- Блокноты экспериментов: [experiment_1.ipynb](../examples/experiment_1.ipynb), [experiment_2.ipynb](../examples/experiment_2.ipynb), [experiment_3.ipynb](../examples/experiment_3.ipynb).
- Ноутбуки подготовки данных: [`notebooks/`](../notebooks).
- Исходники агента: [`blocksnet_agent/`](../blocksnet_agent).
- Справка по инструментам живет в docstring-ах и доступна агенту через `find_tools` / `get_tool_help`.

## Кратко

```python
from blocksnet_agent import BlocksNetAgent

agent = BlocksNetAgent(model="openai/gpt-4o-mini", max_iterations=10)
result = agent.run("Оцени обеспеченность сервисами и предложи, где усилить.")

print(result["output"])       # структурированный ответ
print(result["confidence"])   # самооценка 0.0–1.0
print(result["run_dir"])      # каталог с CSV, картами, run_log
```
