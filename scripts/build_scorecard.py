from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blocksnet_agent.metrics import dimension_scores


DEFAULT_RESULTS_DIR = ROOT / "docs" / "bench"
DIMENSIONS = ("D1", "D2", "D3", "D4")
D4_JUDGE_CRITERIA = ("coherence", "justification", "uncertainty", "metacognition")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BNA-Eval scorecard from auto and judge CSV files.")
    parser.add_argument("--runs", type=Path, required=True, help="CSV produced by scripts/run_bench.py.")
    parser.add_argument("--judge", type=Path, default=None, help="Judge long CSV produced by scripts/eval_judge.py.")
    parser.add_argument("--out-prefix", type=Path, default=None, help="Output prefix without suffix.")
    args = parser.parse_args()

    prefix = args.out_prefix or DEFAULT_RESULTS_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    artifacts = build_scorecard(args.runs, args.judge, prefix)
    print(f"Saved scorecard: {artifacts['wide']}")
    print(f"Saved long rows: {artifacts['long']}")
    print(f"Saved markdown: {artifacts['markdown']}")
    return 0


def build_scorecard(
    runs_path: Path | str,
    judge_path: Path | str | None = None,
    out_prefix: Path | str | None = None,
) -> dict[str, Path]:
    runs = read_csv(Path(runs_path))
    judge_rows = read_csv(Path(judge_path)) if judge_path else []
    judge_index = _judge_medians(judge_rows)
    per_run = [_score_run(row, judge_index.get(_run_key(row), {})) for row in runs]
    long_rows = _dimension_long_rows(per_run, judge_index)
    question_rows = _aggregate(per_run, group_fields=["id", "category", "question"])
    category_rows = _aggregate(per_run, group_fields=["category"])

    prefix = Path(out_prefix) if out_prefix else DEFAULT_RESULTS_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    wide_path = prefix.with_suffix(".csv")
    long_path = prefix.with_suffix(".long.csv")
    md_path = prefix.with_suffix(".md")
    category_path = prefix.with_name(prefix.name + ".category.csv")

    write_csv(wide_path, question_rows)
    write_csv(long_path, long_rows)
    write_csv(category_path, category_rows)
    md_path.write_text(_markdown_report(question_rows, category_rows, per_run), encoding="utf-8")
    return {"wide": wide_path, "long": long_path, "category": category_path, "markdown": md_path}


def build_scorecard_frames(runs_path: Path | str, judge_path: Path | str | None = None):
    import pandas as pd

    runs = read_csv(Path(runs_path))
    judge_rows = read_csv(Path(judge_path)) if judge_path else []
    judge_index = _judge_medians(judge_rows)
    per_run = [_score_run(row, judge_index.get(_run_key(row), {})) for row in runs]
    return (
        pd.DataFrame(_aggregate(per_run, group_fields=["id", "category", "question"])),
        pd.DataFrame(_aggregate(per_run, group_fields=["category"])),
        pd.DataFrame(_dimension_long_rows(per_run, judge_index)),
    )


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _score_run(row: dict[str, Any], judge_scores: dict[str, float]) -> dict[str, Any]:
    auto = {}
    if all(_float(row.get(dim)) is not None for dim in DIMENSIONS):
        auto = {dim: _float(row.get(dim), 0.0) for dim in DIMENSIONS}
        auto["composite"] = _float(row.get("composite"), None)
    else:
        auto = dimension_scores(row)

    d1_judge = _normalise_1_5(judge_scores.get("framing"))
    d4_judge = _optional_mean([_normalise_1_5(judge_scores.get(key)) for key in D4_JUDGE_CRITERIA])
    d1 = _mean([auto.get("D1"), d1_judge])
    d4 = _mean([auto.get("D4"), d4_judge])
    d2 = float(auto.get("D2", 0.0))
    d3 = float(auto.get("D3", 0.0))
    composite = _mean([d1, d2, d3, d4])

    return {
        **row,
        "D1_auto": auto.get("D1"),
        "D4_auto": auto.get("D4"),
        "D1_judge": d1_judge,
        "D4_judge": d4_judge,
        "D1": d1,
        "D2": d2,
        "D3": d3,
        "D4": d4,
        "composite": composite,
    }


def _dimension_long_rows(per_run: list[dict[str, Any]], judge_index: dict[tuple[str, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in per_run:
        key = _run_key(row)
        for dimension in (*DIMENSIONS, "composite"):
            rows.append(
                {
                    "id": row.get("id", ""),
                    "category": row.get("category") or row.get("class", ""),
                    "repeat": row.get("repeat", ""),
                    "question": row.get("question", ""),
                    "dimension": dimension,
                    "score": row.get(dimension),
                    "run_dir": row.get("run_dir", ""),
                }
            )
        for criterion, score in judge_index.get(key, {}).items():
            rows.append(
                {
                    "id": row.get("id", ""),
                    "category": row.get("category") or row.get("class", ""),
                    "repeat": row.get("repeat", ""),
                    "question": row.get("question", ""),
                    "dimension": f"judge_{criterion}",
                    "score": score,
                    "run_dir": row.get("run_dir", ""),
                }
            )
    return rows


def _aggregate(rows: list[dict[str, Any]], group_fields: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in group_fields)
        grouped.setdefault(key, []).append(row)

    result: list[dict[str, Any]] = []
    for key, group in grouped.items():
        item = {field: value for field, value in zip(group_fields, key)}
        item["n"] = len(group)
        for dimension in (*DIMENSIONS, "composite"):
            values = [_float(row.get(dimension)) for row in group]
            clean = [value for value in values if value is not None]
            if clean:
                item[f"{dimension}_median"] = statistics.median(clean)
                item[f"{dimension}_iqr"] = _iqr(clean)
        calls = [_float(row.get("calls")) for row in group]
        wasted = [_float(row.get("wasted_calls")) for row in group]
        if any(value is not None for value in calls):
            item["calls_median"] = statistics.median([value for value in calls if value is not None])
            item["calls_iqr"] = _iqr([value for value in calls if value is not None])
        if any(value is not None for value in wasted):
            item["wasted_calls_median"] = statistics.median([value for value in wasted if value is not None])
        item["run_dirs"] = " | ".join(str(row.get("run_dir", "")) for row in group if row.get("run_dir"))
        result.append(item)
    return sorted(result, key=lambda row: tuple(str(row.get(field, "")) for field in group_fields))


def _judge_medians(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    grouped: dict[tuple[str, str, str], list[float]] = {}
    for row in rows:
        score = _float(row.get("score"))
        if score is None:
            continue
        key = (str(row.get("id", "")), str(row.get("repeat", "")), str(row.get("criterion", "")))
        grouped.setdefault(key, []).append(score)
    result: dict[tuple[str, str], dict[str, float]] = {}
    for (question_id, repeat, criterion), values in grouped.items():
        result.setdefault((question_id, repeat), {})[criterion] = statistics.median(values)
    return result


def _markdown_report(question_rows: list[dict[str, Any]], category_rows: list[dict[str, Any]], per_run: list[dict[str, Any]]) -> str:
    lines = [
        "# BNA-Eval Scorecard",
        "",
        "## By Question",
        "",
        "| Question | Category | D1 | D2 | D3 | D4 | Composite | Calls med/IQR | Wasted |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in question_rows:
        lines.append(
            "| {question} | {category} | {D1} | {D2} | {D3} | {D4} | {comp} | {calls} | {wasted} |".format(
                question=_md(row.get("id") or row.get("question", "")),
                category=_md(row.get("category", "")),
                D1=_fmt(row.get("D1_median")),
                D2=_fmt(row.get("D2_median")),
                D3=_fmt(row.get("D3_median")),
                D4=_fmt(row.get("D4_median")),
                comp=_fmt(row.get("composite_median")),
                calls=f"{_fmt(row.get('calls_median'))}/{_fmt(row.get('calls_iqr'))}",
                wasted=_fmt(row.get("wasted_calls_median")),
            )
        )
    lines.extend(
        [
            "",
            "## By Category",
            "",
            "| Category | N | D1 | D2 | D3 | D4 | Composite |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in category_rows:
        lines.append(
            "| {category} | {n} | {D1} | {D2} | {D3} | {D4} | {comp} |".format(
                category=_md(row.get("category", "")),
                n=row.get("n", ""),
                D1=_fmt(row.get("D1_median")),
                D2=_fmt(row.get("D2_median")),
                D3=_fmt(row.get("D3_median")),
                D4=_fmt(row.get("D4_median")),
                comp=_fmt(row.get("composite_median")),
            )
        )
    lines.extend(["", "## Run Directories", ""])
    for row in per_run:
        if row.get("run_dir"):
            lines.append(f"- `{row.get('id', '')}` repeat {row.get('repeat', '')}: `{row.get('run_dir')}`")
    return "\n".join(lines)


def _run_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("id", "")), str(row.get("repeat", "")))


def _normalise_1_5(value: Any) -> float | None:
    number = _float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, (number - 1.0) / 4.0))


def _mean(values: list[float | None]) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def _optional_mean(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _iqr(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    lower = ordered[:mid]
    upper = ordered[mid:] if len(ordered) % 2 == 0 else ordered[mid + 1 :]
    if not lower or not upper:
        return 0.0
    return statistics.median(upper) - statistics.median(lower)


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: Any) -> str:
    number = _float(value)
    return "" if number is None else f"{number:.2f}"


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
