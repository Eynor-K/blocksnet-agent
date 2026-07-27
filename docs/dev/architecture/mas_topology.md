# Схема взаимодействия BlocksNet ↔ MAS (после рефакторинга)

Заменяет оранжевую зону «BlocksNet» из [MAS.drawio](MAS.drawio) (ред. 2026-06-23),
где BlocksNet был представлен оркестратором `master-urban-planner` с тремя
A2A-субагентами. Основание для пересмотра — [review.md](../decisions/review.md) R1/R2 и
решения [open_questions.md](../decisions/open_questions.md) Q4–Q7.

Формат: mermaid (исходник для воспроизведения в draw.io). Стиль зон, развилок
и блоков «Замечания/Проблемы» сохранён по образцу MAS.drawio, чтобы новая
схема встала в тот же чертёж.

---

## 1. Контекст: место BlocksNet в MAS

```mermaid
flowchart TB
    U(["Запрос пользователя"]) --> ORCH

    subgraph PROSTOR["Зона оркестратора «Простор» — ИПР ИИ-2 / Синапс"]
        ORCH["Агент-оркестратор «Простор»<br/>план → маршрутизация → анализ → сборка"]
    end

    subgraph AGENTS["Агенты «Простор» — ИПР ИИ-5"]
        A1["Агент 1<br/>нормативка"]
        A2["Агент 2<br/>зоны ограничений"]
        A3["Агент 3<br/>ObjectEffects"]
        A4["Агент 4<br/>проверка ПЗЗ"]
    end

    subgraph MCPS["MCP-серверы соседей (Light LLM)"]
        M1["UrbanResponder<br/>RegulatoryRequirements"]
        M2["UrbanSpaceAPI"]
        M3["UrbanResponder<br/>ObjectEffects"]
        M4["PzzCompareAPIMCP"]
        M5["GenPlanMCP"]
    end

    subgraph BN["Зона BlocksNet — реализация на стороне BlocksNet"]
        BNA["blocksnet-urban-planner<br/>A2A-сервис · Agent Card · LLM"]
        BNM["blocksnet-mcp<br/>MCP raw tools · без LLM"]
    end

    ORCH --> A1 --> M1
    ORCH --> A2 --> M2
    ORCH --> A3 --> M3
    ORCH --> A4 --> M4
    ORCH --> M5

    ORCH -->|"A2A JSON-RPC<br/>вопрос по метрикам,<br/>обеспеченности, оптимизации"| BNA
    ORCH -.->|"MCP tools/call<br/>детерминированный шаг,<br/>без LLM"| BNM

    BNA --> RES(["Результат: слои + текст + аннотация"])
    BNM --> RES
    RES --> ORCH
```

**Что изменилось по сравнению со старой схемой.** BlocksNet перестаёт быть
«ещё одним оркестратором с субагентами» и становится **двухвходовым узлом**:
рассуждающий вход (A2A) и детерминированный вход (MCP) — ровно та пара, которую
MAS уже умеет потреблять у соседей (`UrbanSpaceAPI`, `ObjectEffects`, `PzzCompare`).

---

## 2. Зона BlocksNet изнутри

```mermaid
flowchart TB
    IN1["MAS / «Простор»"] -->|A2A JSON-RPC · Bearer · scenario_id| CARD
    IN2["Claude Desktop · Cursor · CI · другой агент"] -->|MCP stdio/HTTP| TOOLS

    subgraph A2A["blocksnet-urban-planner (A2A-сервис)"]
        CARD["Agent Card<br/>/.well-known/agent-card.json"]
        SK["skills:<br/>• run_pipeline (multi-step)<br/>• analyze_urban_question (обёртка)"]
        TM["task_manager<br/>submitted → working →<br/>completed / failed / canceled"]
        AG["BlocksNetAgent<br/>PTR-цикл · RAG по инструментам ·<br/>гипотезы · инварианты M1-M3 / C1-C3"]
        ST1[("state прогона<br/>blocks · acc_mx · result_key")]
        CARD --> SK --> TM --> AG --> ST1
    end

    subgraph MCP["blocksnet-mcp (raw tools)"]
        TOOLS["tools/list — 32 инструмента"]
        SESS["SessionStore<br/>session_id → state · TTL · LRU"]
        ENV["конверт ответа<br/>status · text · artifacts · error_code"]
        TOOLS --> SESS --> ENV
    end

    AG -->|in-process| FACT
    TOOLS -->|in-process| FACT
    FACT["make_tools(state, data_dir, output_dir)<br/>общая фабрика инструментов"]
    FACT --> LIB["blocksnet — детерминированные расчёты"]
    LIB --> DATA[("DATA_DIR / OUTPUT_DIR<br/>по scenario_id")]

    ST1 -.->|"один объект state:<br/>overlay · гипотезы · confidence"| AG
```

**Ключевой инвариант схемы.** Стрелка «агент → инструменты» — **in-process**,
а не по сети. `state`, который пишут инструменты, читает постобработка агента
(`overlay_candidates`, численная верификация гипотез, `confidence_basis`,
`valid_block_ids`). Граница процесса рвёт эти связи тихо — без исключений,
с деградацией качества ответа ([review.md](../decisions/review.md) R2).

Именно поэтому три субагента старой схемы **не** становятся отдельными
сервисами — см. §3.

---

## 3. Судьба субагентов старой схемы

| Старая схема (A2A-субагент) | Новая схема | Инструменты |
|---|---|---|
| `city-blocks-aggregator` | домен инструментов «данные и структура» | `load_blocks`, `build_adjacency_graph`, `compute_density_indicators`, `compute_development_indicators`, `get_block_info` |
| `transport-analytics` | домен «доступность и связность» | `load_accessibility_matrix`, `compute_mean/median/max_accessibility`, `compute_connectivity`, `compute_land_use_accessibility`, `compute_area_accessibility` |
| `optimizer` | домен «оптимизация и сценарии» | `suggest_target_blocks`, `propose_zone_development`, `compute_scenario_provision`, `compute_service_provision`, `compute_shared_provision` |
| `master-urban-planner` | **сам A2A-сервис**: PTR-цикл вместо ручных развилок | все + `find_tools`, `get_tool_help`, `submit_answer` |

**Почему не отдельные сервисы.** Все три домена работают над одним и тем же
`state`: `blocks` (GeoDataFrame кварталов) и `acc_mx` (матрица доступности)
грузятся один раз и переиспользуются. `optimizer` читает результаты
`transport-analytics` через `state[result_key]`. Разнести их по процессам —
это либо гонять GeoDataFrame'ы по сети на каждом шаге, либо потерять связь
результатов; и то и другое хуже по всем осям, кроме организационной.

**Что при этом не теряется.** Домены остаются видимыми снаружи — через
MCP-каталог и через `find_tools`. Оркестратор «Простор» может адресовать
конкретный инструмент детерминированно, не поднимая наш LLM-цикл.

---

## 4. Маршрутизация запроса внутри BlocksNet

Старая схема хардкодила развилки («Вопрос про транспорт?» → агент 2). Новая
оставляет только те решения, которые действительно детерминированы; выбор
инструментов — за PTR-циклом.

```mermaid
flowchart TB
    Q["Запрос от MAS<br/>question + scenario_id + project_id"] --> AUTH{"Bearer валиден?"}
    AUTH -->|Нет| E401["401 · UNAUTHORIZED"]
    AUTH -->|Да| VAL{"question непустой,<br/>scenario_id валиден?"}
    VAL -->|Нет| EVAL["VALIDATION_ERROR"]
    VAL -->|Да| DATA{"Данные сценария<br/>материализованы?"}
    DATA -->|Нет| MAT["Материализация из UrbanDB<br/>в DATA_DIR/scenario_id"]
    MAT --> DATAOK{"Успешно?"}
    DATAOK -->|Нет| ENOD["SCENARIO_NOT_MATERIALIZED"]
    DATAOK -->|Да| PTR
    DATA -->|Да| PTR

    PTR["PTR-цикл: план → выбор инструмента → наблюдение → рефлексия<br/>RAG: find_tools / get_tool_help"]
    PTR --> TOOL["Вызов инструмента (in-process)"]
    TOOL --> INV{"Инварианты M1-M3 / C1-C3<br/>пройдены?"}
    INV -->|Нет| PTR
    INV -->|Да| DL{"Дедлайн / бюджет<br/>итераций исчерпан?"}
    DL -->|Да| PART["submit_answer по накопленному<br/>status = partial"]
    DL -->|Нет| DONE{"Ответ готов?"}
    DONE -->|Нет| PTR
    DONE -->|Да| FIN["submit_answer<br/>status = ok"]
    PART --> OUT
    FIN --> OUT
    OUT["Результат: JSON + артефакты (слои, карты, CSV)"]
```

Развилка «Есть ли исходные данные?» из старой схемы сохранена — но теперь это
не вопрос к пользователю, а материализация по `scenario_id`. Развилки «вопрос
про транспорт / оптимизацию» убраны: их роль выполняет RAG по инструментам,
поэтому добавление нового инструмента не требует правки схемы маршрутизации.

---

## 5. Сценарий A2A: эталонный запрос

Запрос из старой схемы: *«Проверь пешеходную доступность сервисов, и если в
каком-то квартале она ниже средней, предложи оптимальное количество детских
садов и магазинов для этого квартала, исходя из жилой застройки»*.

```mermaid
sequenceDiagram
    participant P as Оркестратор «Простор»
    participant A as blocksnet-urban-planner
    participant T as task_manager
    participant G as BlocksNetAgent (PTR)
    participant F as Инструменты (in-process)
    participant D as DATA_DIR / OUTPUT_DIR

    P->>A: GET /.well-known/agent-card.json
    A-->>P: Agent Card: skills, capabilities.streaming
    P->>A: message/send · run_pipeline<br/>{question, scenario_id, project_id}
    A->>T: создать задачу
    T-->>P: TaskStatus: submitted
    T->>G: запуск в рабочем потоке (RunContext, deadline)
    T-->>P: TaskStatus: working «материализация данных»

    G->>F: load_blocks / load_accessibility_matrix
    F->>D: чтение gpkg / pickle
    F-->>G: сводка (текст), данные осели в state
    T-->>P: working «данные загружены»

    G->>F: compute_mean_accessibility
    F-->>G: сводка + result_key
    T-->>P: working «доступность рассчитана»

    G->>F: suggest_target_blocks (кварталы ниже средней)
    F-->>G: список кварталов
    G->>F: compute_scenario_provision (сады, магазины)
    F->>D: запись CSV / карты
    F-->>G: сводка сценария
    T-->>P: working «сценарий просчитан» + artifact: карта

    G->>G: проверка гипотез, overlay_candidates, confidence
    G->>F: submit_answer (структурный ответ)
    T-->>P: TaskStatus: completed + artifacts
    P->>A: tasks/get
    A-->>P: JSON: plan · result · hypotheses · measured_effects ·<br/>recommendation_blocks · confidence · artifacts
```

Обратите внимание: **гео-слои уходят артефактами** (пути к файлам), а не
инлайном в ответе — см. §7.

---

## 6. Сценарий MCP: детерминированный шаг без LLM

Для случаев, когда оркестратор точно знает, что нужно посчитать — не нужно
поднимать наш LLM-цикл и платить за него.

```mermaid
sequenceDiagram
    participant P as Оркестратор / CI / другой агент
    participant M as blocksnet-mcp
    participant S as SessionStore
    participant F as Инструменты

    P->>M: tools/list
    M-->>P: 32 инструмента + JSON Schema входа
    P->>M: open_session {scenario_id}
    M->>S: создать сессию
    S-->>P: {session_id: "s-7f3a"}

    P->>M: load_blocks {session_id}
    M->>S: получить state сессии
    M->>F: вызов в контексте state
    F-->>M: текст
    M-->>P: {status: ok, text, session_id, artifacts: []}

    P->>M: compute_service_provision {"school", session_id}
    M->>F: результат оседает в state["provision_school"]
    M-->>P: {status: ok, text, artifacts: ["outputs/.../map.png"]}

    P->>M: get_analysis_results {"provision_school", session_id}
    M-->>P: {status: ok, text}
    P->>M: close_session {session_id}
    M->>S: state.clear() — память освобождена
```

Без `session_id` инструменты работают в сессии `"default"` — однопользовательский
режим (Claude Desktop, CI) не требует изменений на стороне клиента.

---

## 7. Контракт границы

### Что BlocksNet предоставляет MAS

| Возможность | Вход | Гарантия |
|---|---|---|
| A2A skill `run_pipeline` | `question`, `scenario_id?`, `project_id?`, `max_iterations?` | task lifecycle, промежуточные статусы, артефакты |
| A2A skill `analyze_urban_question` | то же | блокирующий вызов, тот же JSON, что в контракте v1 |
| MCP `tools/list` + `tools/call` | имя инструмента, аргументы, `session_id?` | детерминированно, без LLM |
| Сессии MCP | `open/close/session_info` | изоляция состояния, TTL 1800 с, LRU 8 |

### Что BlocksNet требует от MAS

| Требование | Зачем |
|---|---|
| `Authorization: Bearer <token>` | при `AUTH_ENABLED=true` |
| `scenario_id` / `project_id` | выбор данных; без них — дефолтный `DATA_DIR` |
| Доступ к UrbanDB (`URBANDB_URL`, `URBANDB_TOKEN`) | материализация сценария |
| Терпимость к `status="partial"` | дедлайн не отменяет ответ, а усекает его |
| Один `scenario_id` на сессию MCP | смена → `SESSION_SCENARIO_MISMATCH`, нужна новая сессия |

### Коды ошибок на границе

| Код | Когда | Что делать оркестратору |
|---|---|---|
| `VALIDATION_ERROR` | пустой `question`, невалидный `scenario_id` | исправить запрос, не повторять как есть |
| `UNAUTHORIZED` (401) | нет/невалиден токен | обновить токен |
| `FORBIDDEN` (403) | нет доступа к сценарию | не повторять |
| `SCENARIO_NOT_MATERIALIZED` | UrbanDB недоступна | повторить позже |
| `LLM_NOT_CONFIGURED` | agent-tool без `CHAT_URL`/`API_KEY` | использовать A2A-вход |
| `SESSION_NOT_FOUND` | сессия истекла по TTL | `open_session` заново |
| `SESSION_SCENARIO_MISMATCH` | смена сценария в сессии | новая сессия |
| `TOOL_FAILED` | инструмент вернул текст-ошибку | читать `text`, менять аргументы |
| `TOOL_EXCEPTION` | исключение внутри инструмента | эскалация, это дефект |
| `DEADLINE_EXCEEDED` / `status=partial` | вышло время | использовать частичный результат |

---

## 8. Замечания и обязательства (в формате блоков старой схемы)

На старой схеме соседи собрали замечания вида «метод возвращает 200 000 –
1 500 000 токенов на вызов, контекст БЯМ переполняется». Фиксируем встречные
обязательства BlocksNet, чтобы не воспроизвести ту же проблему.

> **Обязательство 1 — контекст-бюджет.**
> Инструменты возвращают **текстовые сводки фиксированного размера**
> (агрегаты, топ-N, статистики), а не гео-выгрузки. Поквартальные данные и
> слои отдаются **артефактами** — путями к файлам в `OUTPUT_DIR`. Ни один
> инструмент не возвращает GeoJSON инлайном.

> **Обязательство 2 — предсказуемая стоимость.**
> У A2A-задачи есть бюджет итераций (`MAX_ITERATIONS`, по умолчанию 24) и
> дедлайн (`DEADLINE_SEC`, 480 с). По исчерпании — `status="partial"` с
> накопленным результатом, а не отказ и не бесконечный прогон.

> **Обязательство 3 — детерминированный обход LLM.**
> Любой шаг, который оркестратор умеет спланировать сам, доступен через MCP
> без нашего LLM-цикла. Это прямой ответ на «не хочу платить контекстом за
> то, что знаю точно».

> **Обязательство 4 — самоописание.**
> `tools/list` отдаёт JSON Schema входа для всех инструментов; `find_tools`
> и `get_tool_help` дают полную справку (параметры, контракт, подводные
> камни) детерминированно, без обращения к LLM. Подбор параметров с 422
> и перебором — не наш сценарий.

### Открытые вопросы к MAS

1. **Streaming или polling?** Agent Card объявляет `capabilities.streaming=true`.
   Нужен ли «Простору» поток `TaskStatusUpdateEvent` или достаточно
   `tasks/get` по завершении? От этого зависит объём шага 05.
2. **Формат артефактов.** Отдаём пути в разделяемом volume или ссылки для
   скачивания через HTTP? Первое дешевле, второе — обязательно, если сервисы
   разъедутся по разным хостам.
3. **Кто материализует сценарий** — BlocksNet сам ходит в UrbanDB или MAS
   кладёт данные в согласованный `DATA_DIR`? Влияет на шаг 06.
4. **Push notifications** — сейчас `false`. Нужны ли для длинных прогонов?
5. **Идентичность сессии.** Склеивать `session_id` MCP со `scenario_id`
   автоматически или оставить независимыми?

---

## 9. Соответствие старой схеме

| Элемент MAS.drawio (2026-06-23) | В новой схеме |
|---|---|
| «Зона деятельности агента-оркестратора BlocksNet» | сохранена как зона, внутри — два сервиса вместо четырёх агентов |
| `master-urban-planner` | `blocksnet-urban-planner` (A2A-сервис) |
| `city-blocks-aggregator` / `transport-analytics` / `optimizer` | домены инструментов, не сервисы (§3) |
| «Субагенты (реализация на стороне BloksNet)» | заменено на «MCP raw tools» — второй вход в ту же зону |
| Развилки «Вопрос про транспорт / оптимизацию?» | сняты, заменены PTR-циклом + RAG (§4) |
| Развилка «Есть ли исходные данные?» | сохранена как материализация по `scenario_id` |
| «Промежуточный результат BloksNet» | `TaskStatusUpdateEvent` + артефакты |
| «Анализ результата отработки запроса» / «План окончен?» | остаётся на стороне «Простора», не дублируется у нас |
| todowrite-таблица на 6 шагов | сохраняется как эталонный сценарий приёмки (§5) |
| Блоки «Замечания/Проблемы» | §8, встречные обязательства |

## 10. Как воспроизвести в draw.io

Зоны и цвета — по образцу MAS.drawio, чтобы схема встала в общий чертёж:

| Зона | Заливка |
|---|---|
| Зона BlocksNet | `#FFE6CC` (оранжевая, как в оригинале) |
| A2A-сервис | `#E1D5E7` (фиолетовая, как блоки агентов) |
| MCP-сервер | `#D5E8D4` (зелёная, как MCP-серверы соседей) |
| Общая фабрика инструментов | `#DAE8FC` (голубая) |
| Обязательства / замечания | `#D5E8D4` с рамкой, как блоки «Замечания/Проблемы» |

Порядок листов: §1 — контекст (вместо текущей общей страницы), §2 — врезка
по зоне BlocksNet (заменяет оранжевую зону), §5–6 — два sequence-листа,
§4 — flowchart маршрутизации.
