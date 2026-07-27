# Индекс `blocksnet_agent/`

Назначение: переносимое рассуждающее ядро агента городской аналитики из соседнего проекта
`blocksnet-agent`.

Для локального MVP пакет перенесен **как есть**. MCP-репозиторий не должен менять логику PTR-цикла,
инвариантов, tool-calling и доменных расчетов без отдельной задачи. Текущая версия дополнена
слоем P1.1 (терминальный `submit_answer` для структурного ответа), P1.2 (авторитетная `confidence`
+ `confidence_self` + `confidence_basis`) и P1.6 (`overlay_candidates` как fallback для
`recommendation_blocks`); всё это инвариантно для MCP-слоя.

## Состав

| Файл или папка | Роль |
|---|---|
| `__init__.py` | Публичный API: `BlocksNetAgent`, `AgentResult` (с полями `submitted_answer`, `overlay_recommendations`, `overlay_meta`, `confidence_basis`) |
| `agent.py` | Основной агент, запуск tool-calling, инварианты, confidence, **терминальный `submit_answer`** (P1.1) |
| `hypotheses.py` | PTR-цикл: генерация, проверка и ревизия гипотез; `overlay_candidates` для P1.6 |
| `prompts.py` | System prompt и формат ответа |
| `config.py` | Настройки и загрузка окружения |
| `llm.py` | OpenAI-compatible LLM |
| `runtime.py` | `outputs/run_*`, `run_log`, deadline, прогресс, регистрация артефактов |
| `metrics.py` | Метрики и проверки, используемые агентом |
| `tools/` | Доменные инструменты BlocksNet и RAG-справка: `data`, `network`, `provision`, `services`, `indicators`, `optimize`, `viz`, `registry`, `demand`; T1.2-мемоизация, P0.4-dedup failed-вызовов |

## Что не переносить в этот пакет

Eval-скрипты, notebooks, HTML-отчеты и runtime-outputs из `blocksnet-agent` не относятся к локальному
MCP MVP. Если они понадобятся позже, индексировать их отдельно.

## Источник

Upstream-контекст: `P:\AI_asistent\ITMO\blocksnet-agent`.
