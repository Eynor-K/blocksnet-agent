"""Полный прогон ноутбука examples/test_visualization.ipynb: 10 вопросов на saint_petersburg.

Каждый run_question пишет свой каталог в examples/saint_petersburg/experiments/runs/.
В конце — печатает JSON-сводку по всем 10 ранам.

ВАЖНО: stdout flush после каждого вопроса (python -u), чтобы progress был виден
даже в pipe. Модель и max_iterations берутся как в ноутбуке.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/root/workflow/projects/ITMO/blocksnet-mcp")
sys.path.insert(0, str(ROOT))

from examples._lib.run_mcp import (
    prepare_city,
    select_block_id,
    run_question,
    summarize_run,
)

CITY = "saint_petersburg"
MODEL = "deepseek-v4-pro"
# MAX_ITERATIONS=6 — по отчёту docs/reports/run_quality_report_20260709_spb.md §4.1:
# с 3 итерациями модель не доходила до compute_scenario_provision (measured_effects пуст),
# с 24 — падала по таймауту на длинных батч-расчётах (run 20260709-120825-saint_petersburg-block-348d67).
# 6 — компромисс: модель успеет сделать compute_service_provision + compute_scenario_provision
# для одного сервиса и выдать измеренный эффект за разумное время.
MAX_ITERATIONS = 6
CALL_TIMEOUT = 5400.0  # 1.5ч клиент / 89 мин сервер (DEADLINE_SEC = CALL_TIMEOUT - 60)

QUESTIONS = [
    ("spb_overview",       "Дай общую картину того, насколько город обеспечен объектами повседневного спроса — что в избытке, чего не хватает, есть ли 'мёртвые зоны'. Чтобы не уходить в длинные батч-расчёты, для обзора достаточно 5–7 ключевых сервисов на твой выбор (например, магазин у дома, пекарня, автобусная остановка, кафе, банк, школа, поликлиника) — этого хватит, чтобы выделить 'мёртвые зоны'."),
    ("spb_school_closure", "В квартале 6521 закрыли школу. Что изменится в районе с точки зрения доступности школьного образования?"),
    ("spb_10min_city",     "Если бы город перешёл на стандарт 10-минутной пешеходной доступности для повседневных услуг — какие кварталы выпали бы из обеспеченных?"),
    ("spb_connectivity",   "Есть ли в городе кварталы, которые формально обеспечены услугами, но до них сложно добраться (низкая связность)?"),
    ("yss_overview",       "Как в целом выглядит обеспеченность города услугами первой необходимости?"),
    ("yss_new_district",   "Если в одном из окраинных кварталов построят новый ЖК на 50000 жителей — какие объекты нужно туда добавить, чтобы обеспеченность не упала?"),
    ("yss_equity",         "Есть ли в городе кварталы, которые статистически 'забыты' — мало жителей, мало услуг, плохая доступность?"),
    ("u2_pharmacy",        "Где в городе жители дальше всего от ближайшей аптеки?"),
    ("b_impossible",       "Какая средняя температура воздуха в каждом квартале?"),
    ("b_false_premise",    "Опиши распределение школ по районам."),
]

print(f"[runner] start: CITY={CITY} MODEL={MODEL} MAX_ITERATIONS={MAX_ITERATIONS} CALL_TIMEOUT={CALL_TIMEOUT}", flush=True)

prep = prepare_city(CITY)
print(f"[runner] prep.ready={prep.ready} reason={prep.reason} block_count={prep.block_count}", flush=True)
if not prep.ready:
    sys.exit(2)

block = select_block_id(prep)
BLOCK_ID = block["block_id"]
print(f"[runner] BLOCK_ID={BLOCK_ID} method={block['method']}", flush=True)

t_start = time.monotonic()
results = []
for idx, (qkey, qtext) in enumerate(QUESTIONS, 1):
    t0 = time.monotonic()
    print(f"\n[runner] [{idx}/{len(QUESTIONS)}] {qkey}: '{qtext[:80]}{'...' if len(qtext) > 80 else ''}'", flush=True)
    try:
        r = run_question(
            city=CITY,
            question_key=qkey,
            question=qtext,
            model=MODEL,
            max_iterations=MAX_ITERATIONS,
            block_id=BLOCK_ID,
            call_timeout=CALL_TIMEOUT,
        )
    except Exception as exc:
        print(f"[runner] {qkey} EXCEPTION: {type(exc).__name__}: {exc}", flush=True)
        results.append({"qkey": qkey, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        continue
    s = summarize_run(r)
    s["qkey"] = qkey
    s["duration_sec"] = round(time.monotonic() - t0, 1)
    print(f"[runner] {qkey} status={s['status']} confidence={s['confidence']} duration={s['duration_sec']}s run_dir={s['run_dir']}", flush=True)
    results.append(s)

total = round(time.monotonic() - t_start, 1)
print(f"\n[runner] DONE: {len(results)} runs in {total}s", flush=True)

# JSON-сводка в stdout (для последующего парсинга).
print("\n===JSON_BEGIN===", flush=True)
print(json.dumps({"city": CITY, "model": MODEL, "total_sec": total, "results": results}, ensure_ascii=False, indent=2), flush=True)
print("===JSON_END===", flush=True)