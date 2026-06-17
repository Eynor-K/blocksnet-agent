# План создания BNA-Eval (с блокнотом запуска)

**Дата:** 2026-06-16 · **Статус:** на согласование.
**Методика:** [docs/evaluation/README.md](../evaluation/README.md) (4 измерения D1–D4, гибрид
авто-метрики + LLM-судья-ансамбль, структурные эталоны, скоркарта).
**Назначение:** реализовать оценку и дать **блокнот `examples/evaluation.ipynb`** как единую точку
запуска (по образцу `experiment_1/2.ipynb`).

---

## 0. Что уже есть и что строим

**Есть:**
- `scripts/run_bench.py` — гоняет агента N× на вопрос, читает `run_log.json`, считает авто-метрики,
  пишет `results_*.csv` + `*.summary.csv` (медиана/дисперсия по вопросу).
- `blocksnet_agent/metrics.py` — `run_metrics(...)`: `groundedness`, `measuredness`, `concreteness`,
  `wasted_calls`, `index_usage`, `selection_correctness`, `hypothesis_status_metrics`, и пр.
- `docs/bench/questions.yaml` — вопросы (нужны поля `expected_*`).

**Строим (4 куска + блокнот):**
1. **Данные:** `questions.yaml` с `expected_*` для 18 вопросов (раздел 6 README).
2. **Авто-метрики:** дополнить `metrics.py` недостающими сигналами + свёртка в измерения D1–D4.
3. **LLM-судья:** `scripts/eval_judge.py` — ансамбль судей (Pydantic structured output) для D1/D4.
4. **Скоркарта:** `scripts/build_scorecard.py` — объединение авто+судья → баллы измерений → wide/long + md.
5. **Блокнот:** `examples/evaluation.ipynb` — оркестрация и визуализация.

---

## 1. Принципы реализации
- **Переиспользуем `run_bench.py`** как слой прогона агента (не дублируем).
- **Доменная нейтральность:** `expected_*` и рубрики — только оффлайн, в рантайм агента не попадают.
- **Блокнот — тонкий оркестратор:** вся логика в `metrics.py`/`scripts/*`, блокнот их вызывает и
  отображает (повторяемость, переиспользование из CLI и CI).
- **Дорого ⇒ кэш:** прогоны агента сохраняются в CSV; блокнот умеет переиспользовать готовый
  `results_*.csv`, чтобы не гонять агента заново ради переоценки судьёй/скоркарты.
- **Fail-open у судьи:** сбой судьи по критерию → `score=None` + причина, не падение всего прогона.

---

## 2. Этапы

### ЭТАП 1 — Данные: `questions.yaml` с эталонами
- **Что.** Перенести 18 вопросов (README раздел 6) в `docs/bench/questions.yaml` с полями:
  `id`, `question`, `category` (A/B/C/D/E), `expected_entity`, `expected_tools`,
  `expects_grounding`, `expects_measured`, `expects_out_of_model` (для Q7/Q17), `notes`.
- **Согласование имён с `run_bench.py`:** сейчас он читает `question.get("class")` — переименовать в
  `category` (или поддержать оба ключа).
- **Файлы:** `docs/bench/questions.yaml`, мелкая правка `scripts/run_bench.py`.
- **Критерий:** `run_bench.py --n 1` проходит по всем 18 вопросам, `selection_correctness` считается.

### ЭТАП 2 — Авто-метрики и свёртка в измерения
- **Добавить в `metrics.py` (чистые функции над `steps`/`output_text`/`saved_files`):**
  - `tool_error_rate(steps)` — доля наблюдений-ошибок;
  - `self_correction(steps)` — была ошибка инструмента, затем успешный вызов того же семейства;
  - `per_block_grounding(output_text, steps, expected_entity)` — при названной сущности метрики взяты
    поквартально (нет подмены «город→квартал»);
  - `artifact_discipline(saved_files, category)` — число артефактов в бюджете (для diagnostic/robustness — мало);
  - `confidence_calibration(confidence, groundedness)` — `1 − |confidence − groundedness|`;
  - `ptr_quality(output_text)` — доля фальсифицируемых предсказаний × наличие ≥1 supported/refuted.
- **Свёртка измерений** (новая `dimension_scores(...) -> {D1,D2,D3,D4}` и `scorecard(run, judge=None)`),
  каждая 0..1; веса в `EVAL_WEIGHTS` (по умолчанию равные, настраиваются). Авто-часть D1/D4 считается
  всегда; судейская часть подмешивается, если переданы оценки судьи.
- **Файлы:** `blocksnet_agent/metrics.py`.
- **Критерий:** `scorecard(run)` (без судьи) возвращает D2/D3 и авто-часть D1/D4 для любого прогона.

### ЭТАП 3 — LLM-судья (ансамбль, заимствование fp2mp-eval)
- **`scripts/eval_judge.py`:**
  - Pydantic-модели: `Dimension(score:int 1..5, evidence:str, commentary:str)` и
    `Evaluation(framing, coherence, justification, uncertainty, metacognition: Dimension)` —
    рубрики D1 (framing) и D4 (coherence/justification/uncertainty/metacognition).
  - `EVAL_PROMPT` — строгий критик; оценивает ОТВЕТ+трейс относительно вопроса, НЕ переоценивает
    вопрос; опирается только на приведённый трейс. Якорная шкала 1–5 (README раздел 3).
  - `judge_case(case, n_judges=5, judge_model, max_workers)` — параллельный ансамбль через
    `ThreadPoolExecutor`, `with_structured_output(Evaluation)`, temperature=0; возвращает
    `list[Evaluation]`.
  - Вход «case» = один прогон агента: `{question, final_answer, sections, tool_calls(ledger+обсервации)}`
    — собирается из `run_log.json` по `run_dir` из `results_*.csv`.
  - `judges_to_long_df(...)` — long-формат (question, repeat, judge, criterion, score, evidence, commentary).
- **CLI:** `python scripts/eval_judge.py --runs docs/bench/results_<дата>.csv --judges 5 --judge-model <m>`
  → `docs/bench/judge_<дата>.csv`.
- **Файлы:** новый `scripts/eval_judge.py`.
- **Критерий:** на собранных прогонах судья отдаёт по 5 оценок на критерий с `evidence`/`commentary`;
  сбой одного критерия не валит прогон.

### ЭТАП 4 — Скоркарта и отчёт
- **`scripts/build_scorecard.py`:**
  - вход: `results_*.csv` (авто) + `judge_*.csv` (судья);
  - на каждый (вопрос×прогон) собирает D1–D4 (авто-сигналы + медиана судейских 1–5 → `(s−1)/4`),
    композит;
  - агрегирует по вопросу и по категории: **медиана + IQR** по N прогонам;
  - **экспорт:** `eval_<дата>.csv` (wide: вопрос×измерение) и `eval_<дата>.long.csv` (детальный),
    `eval_<дата>.md` (скоркарта + ссылки на `run_dir` для ручной проверки).
- **Файлы:** новый `scripts/build_scorecard.py`.
- **Критерий:** markdown-скоркарта по 4 измерениям с медианой/IQR и ссылками на трейсы.

### ЭТАП 5 — Блокнот `examples/evaluation.ipynb` (точка запуска)
Структура ячеек (детально — раздел 3).
- **Файлы:** новый `examples/evaluation.ipynb`.
- **Критерий:** блокнот сквозняком: вопросы → прогоны (или загрузка готовых) → судья → скоркарта →
  таблицы/график → drill-down трейса; работает из `examples/` или корня.

### ЭТАП 6 — Валидация и калибровка
- Прогнать на 3–5 вопросах (по 1 повтору) сухой проход; проверить, что D-баллы осмысленны.
- Откалибровать судью на 2–3 вручную размеченных кейсах (сверить балл судьи с экспертным).
- Зафиксировать `baseline` (после Этапа 5 «План улучшений» / текущего кода) как `eval_baseline.*`.

---

## 3. Структура блокнота `examples/evaluation.ipynb`

| # | Тип | Содержимое |
|---|---|---|
| 1 | md | Заголовок, назначение, ссылка на методику `docs/evaluation/README.md`, требования (`.env`) |
| 2 | code | **Параметры:** `MODEL='openai/gpt-4o'`, `N_RUNS=3`, `M_JUDGES=5`, `JUDGE_MODEL=...`, `QUESTIONS=docs/bench/questions.yaml`, `CATEGORIES=None|['A','B',...]`, `REUSE_RESULTS=None` (путь к готовому results_*.csv), `MAX_ITERATIONS=10` |
| 3 | code | **Окружение:** поиск ROOT (как в experiment_*.ipynb), `load_dotenv`, импорты `BlocksNetAgent`, `metrics`, `scripts.eval_judge`, `scripts.build_scorecard`, pandas |
| 4 | code | **Загрузка вопросов** из YAML + фильтр по `CATEGORIES`; вывести таблицу (id, category, question, expected_tools) |
| 5 | code | **Прогон агента** N×: если `REUSE_RESULTS` задан — загрузить CSV; иначе вызвать прогонную логику `run_bench` (импортом функций, не subprocess) → `results_df` (+ сохранить CSV). Прогресс по вопросам |
| 6 | code | **Авто-метрики/измерения:** применить `metrics.scorecard(run)` к каждому прогону (D2/D3 + авто-часть D1/D4) → колонки D-баллов в `results_df` |
| 7 | code | **LLM-судья (ансамбль):** для каждого прогона собрать case из `run_log.json` и вызвать `eval_judge.judge_case(...)`; собрать `judge_long_df`. Кэш в `judge_*.csv`. (Ячейку можно пропустить флагом `RUN_JUDGE=False`) |
| 8 | code | **Скоркарта:** `build_scorecard(...)` → `scorecard_df` (вопрос × D1–D4 + композит, медиана/IQR), `category_df` (агрегат по категориям) |
| 9 | code | **Отображение:** таблица скоркарты (стилизованная), агрегат по категориям; bar-chart баллов D1–D4 по категориям; таблица «здоровья» (wasted_calls, calls med/IQR, hyp_* доли) |
| 10 | code | **Drill-down (ручная проверка):** выбрать `QUESTION_ID` + `REPEAT` → показать полный трейс из `run_log.md` (вопрос, леджер гипотез со статусами, все вызовы с аргументами/наблюдениями, секции ответа) + судейские `evidence`/`commentary` по критериям. Реализует принцип «логирование для ручной проверки» |
| 11 | code | **Сохранение:** `eval_<дата>.csv/.long.csv/.md` в `docs/bench/`; печать пути |
| 12 | md | Как читать скоркарту (ориентиры из README раздел 8); как сравнивать с baseline |

Блокнот **тонкий**: вычисления — в `metrics.py`/`scripts/*`, чтобы те же шаги шли и из CLI/CI.

---

## 4. Сводная таблица и порядок

| Этап | Что | Файлы | Усилие | Риск |
|---|---|---|---|---|
| 1 | questions.yaml + expected_* | docs/bench/questions.yaml, run_bench.py | S | низ |
| 2 | авто-метрики + dimension_scores/scorecard | metrics.py | M | низ |
| 3 | LLM-судья ансамбль | scripts/eval_judge.py | M | сред (стоимость/парсинг) |
| 4 | сборка скоркарты | scripts/build_scorecard.py | M | низ |
| 5 | блокнот запуска | examples/evaluation.ipynb | M | низ |
| 6 | валидация/калибровка | docs/bench/eval_baseline.* | S | низ |

**Порядок:** 1 → 2 → (сухой прогон авто-части в блокноте) → 3 → 4 → 5 → 6.
Авто-часть (1–2) даёт ценность сразу; судья (3) и скоркарта (4) — поверх; блокнот (5) связывает.

---

## 5. Критерии готовности
1. `examples/evaluation.ipynb` сквозняком даёт скоркарту по 4 измерениям с медианой/IQR на 18 вопросах.
2. Авто-метрики покрывают D2/D3 и авто-часть D1/D4; судья-ансамбль покрывает D1/D4 со `score+evidence+commentary`.
3. Drill-down показывает полный трейс прогона + судейские обоснования — пригодно для ручной проверки.
4. Те же вычисления доступны из CLI (`run_bench.py`, `eval_judge.py`, `build_scorecard.py`) — блокнот не монолит.
5. Эталоны/рубрики не протекают в рантайм агента; прогон вопроса-генерализации это подтверждает.
6. Зафиксирован `eval_baseline.*` для сравнения версий.

---

## 6. Выходные артефакты
- `docs/bench/results_<дата>.csv` (+`.summary.csv`) — прогоны агента + авто-метрики.
- `docs/bench/judge_<дата>.csv` — оценки судей (long).
- `docs/bench/eval_<дата>.csv` / `.long.csv` / `.md` — скоркарта и отчёт.
- `docs/bench/eval_baseline.*` — точка отсчёта.

---

## 7. Открытые вопросы на согласование
- **Модель судьи:** какая (рекомендуется отличная от агента; напр. сильная не-gpt-4o), и доступна ли в
  вашем OpenAI-совместимом бэкенде `FP2MP_CHAT_URL`.
- **N_RUNS / M_JUDGES:** дефолт 3/5 — устраивает или менять (цена прогона)?
- **Графики в блокноте:** matplotlib bar-chart по измерениям — нужен или хватит таблиц?
