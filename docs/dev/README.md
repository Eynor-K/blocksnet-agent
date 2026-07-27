# `docs/dev/` — материалы разработки

Эта папка содержит **всё, что относится к процессу разработки и принятым
решениям, но не описывает текущее состояние продукта**. Актуальная
документация продукта — в [`../`](../) (см. [../README.md](../README.md)).

Если вы читаете проект впервые и хотите подключиться — начните с
[`../README.md`](../README.md) и [`../architecture.md`](../architecture.md).
`docs/dev/` нужен, когда непонятно **почему** сделано именно так, или
нужно поднять предыдущий план / отложенные задачи.

---

## Разделы

| Подпапка | Что внутри | Когда открывать |
|---|---|---|
| [`plans/`](plans/) | Планы реализации (a2a-рефакторинг, MAS-интеграция) | При старте нового этапа работ или восстановлении контекста предыдущего |
| [`architecture/`](architecture/) | Целевая архитектура (vision), MAS-топология, диаграммы | При обсуждении «где что стоит в системе» и интерфейса с MAS |
| [`decisions/`](decisions/) | Reasoning, open questions, review | Когда нужно понять, **почему** было принято решение (а не просто «как сделано») |
| [`spikes/`](spikes/) | Технические спайки (a2a-sdk 1.1.1, baseline, tools snapshot) | При апгрейде SDK / воспроизведении старого спайка |
| [`deferred/`](deferred/) | Отложенные задачи + pre-deployment checklist | При планировании следующих этапов ИЛИ перед разверткой |

---

## Связь с актуальной документацией

| Актуальный документ | Соответствующий dev-материал |
|---|---|
| [../architecture.md](../architecture.md) | [architecture/target_architecture.md](architecture/target_architecture.md) — целевая vision; [decisions/reasoning.md](decisions/reasoning.md) — почему именно такая |
| [../tool_contract.md](../tool_contract.md) (v2) | [decisions/open_questions.md](decisions/open_questions.md) Q1–Q7 — принятые решения по контракту |
| [../a2a_agent_card.md](../a2a_agent_card.md) | [spikes/a2a_sdk_1_1_1.md](spikes/a2a_sdk_1_1_1.md) — откуда взяты имена полей (фактический спайк SDK) |
| [../deployment.md](../deployment.md) | [plans/a2a_refactor/07-docker.md](plans/a2a_refactor/07-docker.md) — критерии готовности Docker-шага |
| [../reports/a2a_refactor_completion_report.md](../reports/a2a_refactor_completion_report.md) | [plans/a2a_refactor/](plans/a2a_refactor/) — все шаги плана + [deferred/](deferred/) — что осталось |

---

## Соглашения

- `plans/` — пошаговые инструкции с критериями готовности; **исполняемый** документ.
- `decisions/` — фиксация выбора; обновляется при смене решения, но не правится задним числом.
- `architecture/` — vision; конфликты с `../architecture.md` (актуальным) разрешаются в пользу актуального.
- `spikes/` — артефакт исследования; может быть удалён после полного внедрения в код.
- `deferred/` — задачи вне текущего скоупа; имеют приоритет «когда-нибудь».

## Когда архивировать

После приёмки работы Игорем содержимое `plans/a2a_refactor/` (шаги 00-08) и
`deferred/a2a_refactor_deferred.md` **должно быть заархивировано** в
`docs/archive/a2a_refactor/` (см. план шага 08). До этого — рабочий материал.