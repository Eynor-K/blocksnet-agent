from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blocksnet_agent.metrics import run_metrics


DEFAULT_QUESTIONS = ROOT / "docs" / "bench" / "questions.yaml"
DEFAULT_RESULTS_DIR = ROOT / "docs" / "bench"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BlocksNetAgent benchmark questions with auto-metrics.")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--n", type=int, default=3, help="Repeats per question.")
    parser.add_argument("--out", type=Path, default=None, help="CSV output path.")
    parser.add_argument("--model", default=None, help="Override model from settings/.env.")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--categories", nargs="*", default=None, help="Optional category filter: A B C D E.")
    args = parser.parse_args()

    output_path = args.out or DEFAULT_RESULTS_DIR / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    rows = run_benchmark(
        questions_path=args.questions,
        n=args.n,
        output_path=output_path,
        model=args.model,
        max_iterations=args.max_iterations,
        categories=args.categories,
    )

    _write_summary(output_path.with_suffix(".summary.csv"), rows)
    print(f"Saved benchmark rows: {output_path}")
    print(f"Saved summary: {output_path.with_suffix('.summary.csv')}")
    return 0


def run_benchmark(
    questions_path: Path = DEFAULT_QUESTIONS,
    n: int = 3,
    output_path: Path | None = None,
    model: str | None = None,
    max_iterations: int = 10,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    from blocksnet_agent import BlocksNetAgent

    questions = _load_questions(questions_path)
    if categories:
        allowed = {item.upper() for item in categories}
        questions = [q for q in questions if str(q.get("category") or q.get("class") or "").upper() in allowed]

    out = output_path or DEFAULT_RESULTS_DIR / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    agent = BlocksNetAgent(model=model, max_iterations=max_iterations)
    for question in questions:
        category = question.get("category") or question.get("class", "")
        for repeat in range(1, max(1, n) + 1):
            row = run_one_case(agent, question, repeat=repeat)
            rows.append(row)
            _write_csv(out, rows)
            print(
                f"{row['id']} #{repeat}: D1={row['D1']:.2f}, D2={row['D2']:.2f}, "
                f"D3={row['D3']:.2f}, D4={row['D4']:.2f}, category={category}, "
                f"selection={row['selection_correctness']}, elapsed={row['elapsed']:.1f}s"
            )
    return rows


def run_one_case(agent: Any, question: dict[str, Any], repeat: int = 1) -> dict[str, Any]:
    started = time.perf_counter()
    result = agent.run(question["question"])
    elapsed = time.perf_counter() - started
    run_log = _read_run_log(result.get("run_dir", ""))
    steps = _steps_from_run_log(run_log)
    category = question.get("category") or question.get("class", "")
    metric_values = run_metrics(
        output_text=str(result.get("output", "")),
        steps=steps,
        expected_tools=[str(tool) for tool in question.get("expected_tools", [])],
        expected_entity=question.get("expected_entity"),
        category=str(category),
        saved_files=run_log.get("saved_files", []),
        confidence=result.get("confidence"),
        self_confidence=(result.get("sections", {}) or {}).get("SELF_CONFIDENCE"),
        elapsed=elapsed,
    )
    return {
        "id": question.get("id", ""),
        "category": category,
        "class": category,
        "repeat": repeat,
        "question": question.get("question", ""),
        "expected_entity": question.get("expected_entity", ""),
        "expects_grounding": question.get("expects_grounding", ""),
        "expects_measured": question.get("expects_measured", ""),
        "expects_out_of_model": question.get("expects_out_of_model", ""),
        "run_dir": result.get("run_dir", ""),
        **metric_values,
    }


def _steps_from_run_log(run_log: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "tool": call.get("tool", ""),
            "tool_input": str(call.get("args", "")),
            "observation": str(call.get("observation", "")),
        }
        for call in run_log.get("tool_calls", [])
    ]


def _load_questions(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"{path} is not JSON-compatible YAML and PyYAML is not installed") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, list):
        raise ValueError("questions file must contain a list")
    return [item for item in data if isinstance(item, dict) and item.get("question")]


def _read_run_log(run_dir: str) -> dict[str, Any]:
    if not run_dir:
        return {}
    path = Path(run_dir) / "run_log.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    numeric_fields = [
        "groundedness",
        "measuredness",
        "concreteness",
        "calls",
        "unique_calls",
        "duplicate_calls",
        "artifacts_csv",
        "artifacts_png",
        "confidence",
        "wasted_calls",
        "index_usage",
        "selection_correctness",
        "tool_error_rate",
        "self_correction",
        "per_block_grounding",
        "artifact_discipline",
        "confidence_calibration",
        "ptr_quality",
        "D1",
        "D2",
        "D3",
        "D4",
        "composite",
        "hyp_total",
        "hyp_supported",
        "hyp_refuted",
        "hyp_inconclusive",
        "hyp_abandoned",
        "hyp_supported_rate",
        "hyp_refuted_rate",
        "hyp_inconclusive_rate",
        "elapsed",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("id", "")), []).append(row)
    summary_rows: list[dict[str, Any]] = []
    for question_id, group in grouped.items():
        item: dict[str, Any] = {"id": question_id, "n": len(group)}
        for field in numeric_fields:
            values = [float(row[field]) for row in group if row.get(field) not in (None, "")]
            if not values:
                continue
            item[f"{field}_median"] = statistics.median(values)
            item[f"{field}_variance"] = statistics.pvariance(values) if len(values) > 1 else 0.0
        summary_rows.append(item)
    _write_csv(path, summary_rows)


if __name__ == "__main__":
    raise SystemExit(main())
