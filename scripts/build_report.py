"""Собирает автономный HTML-отчёт BNA-Eval (инфографика, сравнение запусков, средние оценки агента).

Использует уже посчитанные артефакты:
- docs/bench/results_<stamp>.csv         (авто-метрики по каждому прогону)
- docs/bench/eval_<stamp>.csv            (скоркарта авто-только, wide)
- docs/bench/eval_judged_<stamp>.csv     (скоркарта с судьёй, wide)
- docs/bench/judge_<stamp>.csv           (судейские баллы по критериям)
Без внешних зависимостей: графики — инлайновый SVG.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "docs" / "bench"


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else 0.0


CRITS = ["framing", "coherence", "justification", "uncertainty", "metacognition"]
CRIT_DIM = {"framing": "D1", "coherence": "D4", "justification": "D4", "uncertainty": "D4", "metacognition": "D4"}
PALETTE = {"A": "#4f8cff", "B": "#36c2a8", "C": "#f6b73c", "D": "#e8685f", "E": "#9b6dde", "E/D": "#7a8aa0"}


def bar_chart(data, *, width=560, bar_h=26, gap=12, vmax=1.0, fmt="{:.2f}", unit="", pad_left=150, color_fn=None):
    """data: list[(label, value, optional_color)]. Возвращает SVG-строку."""
    rows = len(data)
    height = rows * (bar_h + gap) + gap
    plot_w = width - pad_left - 70
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    # gridlines
    for frac in (0.25, 0.5, 0.75, 1.0):
        x = pad_left + plot_w * frac
        parts.append(f'<line x1="{x:.1f}" y1="{gap}" x2="{x:.1f}" y2="{height-gap}" class="grid"/>')
    for i, item in enumerate(data):
        label, value = item[0], item[1] or 0.0
        color = (item[2] if len(item) > 2 else None) or (color_fn(label) if color_fn else "#4f8cff")
        y = gap + i * (bar_h + gap)
        w = max(2, plot_w * (value / vmax)) if vmax else 2
        parts.append(f'<text x="{pad_left-10}" y="{y+bar_h*0.7:.0f}" class="blabel" text-anchor="end">{label}</text>')
        parts.append(f'<rect x="{pad_left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="5" fill="{color}"/>')
        parts.append(f'<text x="{pad_left+w+8:.1f}" y="{y+bar_h*0.7:.0f}" class="bval">{fmt.format(value)}{unit}</text>')
    parts.append("</svg>")
    return "".join(parts)


def grouped_chart(labels, series, *, width=560, vmax=1.0, pad_left=70):
    """series: list[(name, color, values[])]. Сгруппированные вертикальные столбцы по labels."""
    groups = len(labels)
    n = len(series)
    height = 230
    plot_w = width - pad_left - 20
    plot_h = height - 50
    gw = plot_w / groups
    bw = gw / (n + 0.6)
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    for frac in (0.25, 0.5, 0.75, 1.0):
        y = 10 + plot_h * (1 - frac)
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width-20}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_left-8}" y="{y+4:.1f}" class="axis" text-anchor="end">{frac:.2f}</text>')
    for gi, lab in enumerate(labels):
        gx = pad_left + gi * gw
        for si, (name, color, vals) in enumerate(series):
            v = vals[gi] or 0.0
            bh = plot_h * (v / vmax)
            x = gx + 6 + si * bw
            y = 10 + plot_h - bh
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.9:.1f}" height="{bh:.1f}" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{gx+gw/2:.1f}" y="{height-22}" class="axis" text-anchor="middle">{lab}</text>')
    # legend
    lx = pad_left
    for name, color, _ in series:
        parts.append(f'<rect x="{lx}" y="{height-12}" width="11" height="11" rx="2" fill="{color}"/>')
        parts.append(f'<text x="{lx+15}" y="{height-3}" class="axis">{name}</text>')
        lx += 16 + len(name) * 7.0
    parts.append("</svg>")
    return "".join(parts)


def donut(value, vmax, label, color, sub=""):
    frac = max(0.0, min(1.0, value / vmax))
    r, c = 52, 60
    circ = 2 * 3.14159 * r
    off = circ * (1 - frac)
    return (
        f'<svg viewBox="0 0 120 120" class="donut" role="img">'
        f'<circle cx="{c}" cy="{c}" r="{r}" class="donut-bg"/>'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round" '
        f'stroke-dasharray="{circ:.1f}" stroke-dashoffset="{off:.1f}" transform="rotate(-90 {c} {c})"/>'
        f'<text x="{c}" y="{c-2}" class="donut-val" text-anchor="middle">{label}</text>'
        f'<text x="{c}" y="{c+16}" class="donut-sub" text-anchor="middle">{sub}</text>'
        f"</svg>"
    )


def main() -> int:
    stamp = sys.argv[1] if len(sys.argv) > 1 else "20260617_004403"
    judged_stamp = sys.argv[2] if len(sys.argv) > 2 else "20260617"
    results = read(BENCH / f"results_{stamp}.csv")
    auto = read(BENCH / f"eval_{stamp}.csv")
    judged = read(BENCH / f"eval_judged_{judged_stamp}.csv")
    judge = read(BENCH / f"judge_{stamp}.csv")

    n_runs = len(results)
    n_questions = len(judged)
    # --- agent averages (auto, per run) ---
    avg_calls = mean([fnum(r.get("calls")) for r in results])
    avg_wasted = mean([fnum(r.get("wasted_calls")) for r in results])
    avg_ground = mean([fnum(r.get("groundedness")) for r in results])
    avg_meas = mean([fnum(r.get("measuredness")) for r in results])
    avg_sel = mean([fnum(r.get("selection_correctness")) for r in results])
    avg_conf = mean([fnum(r.get("confidence")) for r in results])
    avg_terr = mean([fnum(r.get("tool_error_rate")) for r in results])

    # --- judged dimension means (по медианам вопросов) ---
    def jmean(col):
        return mean([fnum(r.get(col)) for r in judged])
    D = {d: jmean(f"{d}_median") for d in ("D1", "D2", "D3", "D4")}
    comp = jmean("composite_median")

    # --- judge criteria averages ---
    crit_vals = {c: [] for c in CRITS}
    for row in judge:
        s = fnum(row.get("score"))
        if s is not None and row.get("criterion") in crit_vals:
            crit_vals[row["criterion"]].append(s)
    crit_mean = {c: mean(v) for c, v in crit_vals.items()}
    crit_med = {c: (st.median(v) if v else 0) for c, v in crit_vals.items()}
    # inter-judge agreement
    trip = {}
    for row in judge:
        s = fnum(row.get("score"))
        if s is None:
            continue
        trip.setdefault((row["id"], row["repeat"], row["criterion"]), []).append(s)
    agree = mean([st.pstdev(v) for v in trip.values() if len(v) > 1])

    # --- by category (auto vs judged composite) ---
    def cat_map(rows, col):
        d = {}
        for r in rows:
            d.setdefault(r.get("category", "?"), []).append(fnum(r.get(col)))
        return {k: mean(v) for k, v in d.items()}
    cats = sorted({r.get("category", "?") for r in judged})
    comp_auto = cat_map(auto, "composite_median") if auto and "composite_median" in auto[0] else cat_map(auto, "composite")
    comp_jud = cat_map(judged, "composite_median")
    d_by_cat = {d: cat_map(judged, f"{d}_median") for d in ("D1", "D2", "D3", "D4")}

    # --- per-question table (judged) ---
    qrows = sorted(judged, key=lambda r: -(fnum(r.get("composite_median")) or 0))

    # ---------- build HTML ----------
    kpi = [
        donut(comp, 1.0, f"{comp:.2f}", "#4f8cff", "композит"),
        donut(D["D1"], 1.0, f"{D['D1']:.2f}", "#36c2a8", "D1 поним."),
        donut(D["D2"], 1.0, f"{D['D2']:.2f}", "#9b6dde", "D2 выбор"),
        donut(D["D3"], 1.0, f"{D['D3']:.2f}", "#f6b73c", "D3 использ."),
        donut(D["D4"], 1.0, f"{D['D4']:.2f}", "#e8685f", "D4 выводы"),
    ]

    judge_chart = bar_chart(
        [(c, crit_mean[c], {"framing": "#36c2a8", "uncertainty": "#36c2a8", "metacognition": "#f6b73c",
                            "coherence": "#f6b73c", "justification": "#e8685f"}[c]) for c in CRITS],
        vmax=5.0, fmt="{:.2f}", pad_left=150,
    )
    cat_comp_chart = bar_chart(
        [(c, comp_jud.get(c, 0), PALETTE.get(c, "#888")) for c in cats], vmax=1.0, pad_left=70,
    )
    cmp_chart = grouped_chart(
        cats,
        [("Авто-только", "#c9d4e3", [comp_auto.get(c, 0) for c in cats]),
         ("С судьёй", "#4f8cff", [comp_jud.get(c, 0) for c in cats])],
    )
    dim_chart = grouped_chart(
        cats,
        [("D1", "#36c2a8", [d_by_cat["D1"].get(c, 0) for c in cats]),
         ("D2", "#9b6dde", [d_by_cat["D2"].get(c, 0) for c in cats]),
         ("D3", "#f6b73c", [d_by_cat["D3"].get(c, 0) for c in cats]),
         ("D4", "#e8685f", [d_by_cat["D4"].get(c, 0) for c in cats])],
    )

    def bar_cell(v, color="#4f8cff"):
        w = max(2, (v or 0) * 100)
        return (f'<div class="minibar"><span style="width:{w:.0f}%;background:{color}"></span>'
                f'<b>{(v or 0):.2f}</b></div>')

    qtable = []
    for r in qrows:
        c = fnum(r.get("composite_median")) or 0
        qtable.append(
            f"<tr><td class='qid'>{r['id']}</td><td><span class='tag' style='background:{PALETTE.get(r['category'],'#888')}'>"
            f"{r['category']}</span></td><td class='q'>{r.get('question','')}</td>"
            f"<td>{bar_cell(fnum(r.get('D1_median')), '#36c2a8')}</td>"
            f"<td>{bar_cell(fnum(r.get('D2_median')), '#9b6dde')}</td>"
            f"<td>{bar_cell(fnum(r.get('D3_median')), '#f6b73c')}</td>"
            f"<td>{bar_cell(fnum(r.get('D4_median')), '#e8685f')}</td>"
            f"<td>{bar_cell(c)}</td>"
            f"<td class='num'>{fnum(r.get('calls_median')):.0f}</td>"
            f"<td class='num'>{fnum(r.get('wasted_calls_median')):.0f}</td></tr>"
        )

    html = TEMPLATE.format(
        n_runs=n_runs, n_questions=n_questions, n_judges=3, n_scores=len(judge),
        kpi="".join(kpi),
        comp=f"{comp:.2f}",
        avg_calls=f"{avg_calls:.1f}", avg_wasted=f"{avg_wasted:.2f}", avg_ground=f"{avg_ground:.2f}",
        avg_meas=f"{avg_meas:.2f}", avg_sel=f"{avg_sel:.2f}", avg_conf=f"{avg_conf:.2f}",
        avg_terr=f"{avg_terr:.2f}", agree=f"{agree:.2f}",
        judge_chart=judge_chart, cat_comp_chart=cat_comp_chart, cmp_chart=cmp_chart, dim_chart=dim_chart,
        just_med=f"{crit_med['justification']:.0f}", fram_med=f"{crit_med['framing']:.0f}",
        qtable="".join(qtable),
    )
    out = ROOT / "docs" / "evaluation" / f"report_{stamp}.html"
    out.write_text(html, encoding="utf-8")
    print("saved", out)
    return 0


TEMPLATE = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BNA-Eval — отчёт о качестве BlocksNetAgent</title>
<style>
:root{{--bg:#0f1420;--card:#171e2e;--card2:#1d2536;--ink:#e6ecf5;--muted:#93a1b8;--line:#2a3447;--accent:#4f8cff}}
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(180deg,#0f1420,#0c111b);color:var(--ink);
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;line-height:1.5}}
.wrap{{max-width:1060px;margin:0 auto;padding:32px 22px 60px}}
header h1{{font-size:26px;margin:0 0 4px}}
header p{{color:var(--muted);margin:0}}
.meta{{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0 8px;color:var(--muted);font-size:13px}}
.meta b{{color:var(--ink)}}
h2{{font-size:17px;margin:34px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;justify-content:space-between;margin-top:18px}}
.donut{{width:118px;height:118px}}
.donut-bg{{fill:none;stroke:#222c3e;stroke-width:12}}
.donut-val{{fill:var(--ink);font-size:24px;font-weight:700}}
.donut-sub{{fill:var(--muted);font-size:11px}}
.grid-cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.stat .v{{font-size:22px;font-weight:700}}
.stat .l{{color:var(--muted);font-size:12px;margin-top:2px}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-top:14px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:760px){{.two{{grid-template-columns:1fr}}}}
.chart{{width:100%;height:auto}}
.grid{{stroke:#26304340;stroke-width:1}}
.blabel{{fill:var(--muted);font-size:12.5px}}
.bval{{fill:var(--ink);font-size:12.5px;font-weight:600}}
.axis{{fill:var(--muted);font-size:11px}}
.cap{{color:var(--muted);font-size:12.5px;margin:2px 0 12px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
th,td{{padding:8px 8px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}}
th{{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}}
.qid{{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--muted);white-space:nowrap}}
.q{{max-width:230px}}
.num{{text-align:center;color:var(--muted)}}
.tag{{display:inline-block;color:#0c111b;font-weight:700;font-size:11px;padding:2px 7px;border-radius:6px}}
.minibar{{position:relative;background:#222c3e;border-radius:5px;height:18px;min-width:74px;display:flex;align-items:center}}
.minibar span{{position:absolute;left:0;top:0;bottom:0;border-radius:5px;opacity:.85}}
.minibar b{{position:relative;font-size:11px;padding-left:6px;font-weight:600}}
.findings{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media(max-width:760px){{.findings{{grid-template-columns:1fr}}}}
.find{{background:var(--card2);border-left:3px solid var(--accent);border-radius:8px;padding:12px 14px;font-size:13.5px}}
.find.warn{{border-color:#e8685f}} .find.ok{{border-color:#36c2a8}} .find.note{{border-color:#f6b73c}}
.find h3{{margin:0 0 4px;font-size:13.5px}} .find p{{margin:0;color:var(--muted)}}
footer{{margin-top:34px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:14px}}
.legend{{color:var(--muted);font-size:12px;margin-top:6px}}
</style></head><body><div class="wrap">
<header>
<h1>BNA-Eval — отчёт о качестве BlocksNetAgent</h1>
<p>Гибридная оценка (авто-метрики + ансамбль LLM-судей) на наборе из 18 урбан-вопросов</p>
<div class="meta"><span>Прогон <b>{n_runs}</b> запусков</span><span>Вопросов <b>{n_questions}</b> × 3 повтора</span>
<span>Судей <b>{n_judges}</b> (модель gpt-4o)</span><span>Судейских баллов <b>{n_scores}</b></span>
<span>Модель агента <b>gpt-4o</b></span></div>
</header>

<h2>Средние оценки агента (скоркарта с судьёй)</h2>
<div class="kpis">{kpi}</div>
<div class="grid-cards" style="margin-top:16px">
<div class="stat"><div class="v">{avg_sel}</div><div class="l">выбор инструментов (selection)</div></div>
<div class="stat"><div class="v">{avg_ground}</div><div class="l">заземлённость (groundedness)</div></div>
<div class="stat"><div class="v">{avg_meas}</div><div class="l">измеренность (measuredness)</div></div>
<div class="stat"><div class="v">{avg_conf}</div><div class="l">confidence (средн.)</div></div>
<div class="stat"><div class="v">{avg_calls}</div><div class="l">вызовов на прогон</div></div>
<div class="stat"><div class="v">{avg_wasted}</div><div class="l">пустых вызовов (wasted)</div></div>
<div class="stat"><div class="v">{avg_terr}</div><div class="l">доля ошибок инструмента</div></div>
<div class="stat"><div class="v">±{agree}</div><div class="l">разброс между судьями (σ)</div></div>
</div>

<h2>Инфографика: оценки судей и измерения</h2>
<div class="two">
<div class="panel"><b>Средний балл судьи по критериям</b> <span class="cap">шкала 1–5; justification — слабейшее звено</span>{judge_chart}</div>
<div class="panel"><b>Композитный балл по категориям</b> <span class="cap">A квартал · B город · C диагностика · D комбо · E робастность</span>{cat_comp_chart}</div>
</div>
<div class="panel"><b>Измерения D1–D4 по категориям</b> <span class="cap">D1 понимание · D2 выбор · D3 использование · D4 выводы (с судьёй)</span>{dim_chart}</div>

<h2>Сравнение запусков: авто-только против оценки с судьёй</h2>
<div class="panel"><b>Композит по категориям: два прохода оценки</b>
<span class="cap">судья делает D1 различающим и исправляет перекос measuredness на диагностике (C: D4 0.39→0.57)</span>{cmp_chart}</div>

<h2>Ключевые выводы</h2>
<div class="findings">
<div class="find ok"><h3>✅ Понимание и честность — сильные</h3><p>framing и uncertainty: медиана 5/5. Агент верно трактует задачу и честно помечает ограничения/вне-модельные вопросы.</p></div>
<div class="find ok"><h3>✅ Выбор инструментов надёжен</h3><p>пустых вызовов в среднем {avg_wasted}; ошибок инструмента {avg_terr}. Перебора имён и разгона почти нет.</p></div>
<div class="find warn"><h3>⚠️ Измеренный цикл не запускается</h3><p>measuredness ≈ {avg_meas}: генеративные вопросы «что/где разместить» не доходят до propose→scenario. Это тянет вниз justification (медиана {just_med}).</p></div>
<div class="find note"><h3>◐ Судьи согласованны</h3><p>разброс между 3 судьями σ=±{agree} балла, 0 сбоев — оценки воспроизводимы; даже 3 судей достаточно.</p></div>
</div>

<h2>Скоркарта по вопросам (медиана по 3 повторам, с судьёй)</h2>
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th>ID</th><th>Кат</th><th>Вопрос</th><th>D1</th><th>D2</th><th>D3</th><th>D4</th><th>Композит</th><th>Выз.</th><th>Пуст.</th></tr></thead>
<tbody>{qtable}</tbody></table>
<div class="legend">D1 понимание · D2 выбор инструментов · D3 использование · D4 выводы · мини-бар = балл 0..1</div>
</div>

<footer>BNA-Eval · гибрид авто-метрик и ансамбля LLM-судей (заимствование fp2mp-eval) ·
методика: docs/evaluation/README.md · подробный разбор: docs/evaluation/анализ_eval_20260617.md ·
оценка проведена на сохранённых логах, агент повторно не запускался.</footer>
</div></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
