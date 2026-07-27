"""Smoke-прогон 2 вопросов после P0.5-корректировок."""
import json, sys, time
from pathlib import Path
ROOT = Path("/root/workflow/projects/ITMO/blocksnet-mcp")
sys.path.insert(0, str(ROOT))

from examples._lib.run_mcp import prepare_city, select_block_id, run_question, summarize_run

CITY = "saint_petersburg"
MODEL = "deepseek-v4-pro"
MAX_ITERATIONS = 6
CALL_TIMEOUT = 1200.0  # 20 мин клиент / 19 мин сервер

QUESTIONS = [
    ("smoke_b_impossible",  "Какая средняя температура воздуха в каждом квартале?"),
    ("smoke_school_closure", "В квартале 6521 закрыли школу. Что изменится в районе с точки зрения доступности школьного образования?"),
]

print(f"[smoke] start: CITY={CITY} MODEL={MODEL} MAX_ITERATIONS={MAX_ITERATIONS}", flush=True)
block = select_block_id(prepare_city(CITY))
BLOCK_ID = block["block_id"]
print(f"[smoke] BLOCK_ID={BLOCK_ID}", flush=True)

for qkey, qtext in QUESTIONS:
    t0 = time.monotonic()
    print(f"\n[smoke] {qkey}: '{qtext[:80]}{'...' if len(qtext) > 80 else ''}'", flush=True)
    r = run_question(CITY, qkey, qtext, MODEL, MAX_ITERATIONS, BLOCK_ID, call_timeout=CALL_TIMEOUT)
    s = summarize_run(r)
    s["duration_sec"] = round(time.monotonic() - t0, 1)
    print(f"[smoke] {qkey} status={s['status']} confidence={s['confidence']} duration={s['duration_sec']}s", flush=True)
    print(f"[smoke] {qkey} rec_blocks={s.get('recommendation_blocks', [])[:5]}", flush=True)
    # Если есть mcp_response.json — покажем ключевые поля
    resp_p = Path(s["run_dir"]) / "mcp_response.json"
    if resp_p.exists():
        resp = json.loads(resp_p.read_text(encoding="utf-8"))
        print(f"[smoke] {qkey} salvaged={resp.get('salvaged')} measured={bool(resp.get('measured_effects') or resp.get('measured'))}", flush=True)
        print(f"[smoke] {qkey} rec_blocks (raw)={resp.get('recommendation_blocks')[:5]}", flush=True)