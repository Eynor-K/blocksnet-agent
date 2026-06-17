from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blocksnet_agent.llm import get_chat_model
from blocksnet_agent.metrics import extract_sections


DEFAULT_RESULTS_DIR = ROOT / "docs" / "bench"


class Dimension(BaseModel):
    score: int | None = Field(default=None, ge=1, le=5)
    evidence: str = ""
    commentary: str = ""


class Evaluation(BaseModel):
    framing: Dimension
    coherence: Dimension
    justification: Dimension
    uncertainty: Dimension
    metacognition: Dimension


EVAL_PROMPT = """Ты строгий критик качества ответа BlocksNetAgent.

Оцени ОТВЕТ и ТРЕЙС относительно ВОПРОСА. Не переоценивай сам вопрос и не добавляй внешние знания.
Опирайся только на приведённые вызовы инструментов, наблюдения, секции ответа и ограничения.

Шкала 1-5:
5 отлично, существенных слабостей нет;
4 хорошо, есть мелкие огрехи;
3 приемлемо, есть заметные пробелы;
2 плохо, серьёзные проблемы;
1 очень плохо или критерий отсутствует.

Критерии:
- framing: понял ли агент ключевую сущность, сервис/метрику и намерение задачи.
- coherence: согласованы ли RESULT, REFLECTION, HYPOTHESES и фактический трейс.
- justification: подкреплены ли выводы конкретными наблюдениями инструментов и trade-off.
- uncertainty: честно ли отмечены unverified/inconclusive/LIMITATIONS, особенно для вопросов вне модели.
- metacognition: видна ли проверка процесса, статусы гипотез, самопроверка и корректная остановка.

Для каждого критерия верни score, evidence (короткая цитата/указание на фрагмент трейса) и commentary.
Если критерию невозможно поставить оценку из-за отсутствия данных, score=null и объясни причину."""


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate benchmark runs with an LLM judge ensemble.")
    parser.add_argument("--runs", type=Path, required=True, help="CSV produced by scripts/run_bench.py.")
    parser.add_argument("--out", type=Path, default=None, help="Judge long CSV output path.")
    parser.add_argument("--judges", type=int, default=5, help="Number of independent judge calls per run.")
    parser.add_argument("--judge-model", default=None, help="Judge model id; defaults to project settings.")
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()

    rows = read_csv(args.runs)
    out = args.out or DEFAULT_RESULTS_DIR / f"judge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    for row in rows:
        case = case_from_result_row(row)
        evaluations = judge_case(
            case,
            n_judges=args.judges,
            judge_model=args.judge_model,
            max_workers=args.max_workers,
        )
        all_rows.extend(judges_to_long_rows(row, evaluations))
        write_csv(out, all_rows)
        print(f"{row.get('id', '')} #{row.get('repeat', '')}: {len(evaluations)} judge results")

    print(f"Saved judge rows: {out}")
    return 0


def judge_case(
    case: dict[str, Any],
    n_judges: int = 5,
    judge_model: str | None = None,
    max_workers: int = 4,
) -> list[Evaluation]:
    n = max(1, n_judges)
    workers = max(1, min(max_workers, n))
    results: list[Evaluation] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_judge_once, case, judge_model, index) for index in range(n)]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(_failed_evaluation(str(exc)))
    return results


def judges_to_long_rows(result_row: dict[str, Any], evaluations: list[Evaluation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for judge_index, evaluation in enumerate(evaluations, start=1):
        payload = evaluation.model_dump()
        for criterion, dimension in payload.items():
            rows.append(
                {
                    "id": result_row.get("id", ""),
                    "category": result_row.get("category") or result_row.get("class", ""),
                    "repeat": result_row.get("repeat", ""),
                    "judge": judge_index,
                    "criterion": criterion,
                    "score": dimension.get("score"),
                    "evidence": dimension.get("evidence", ""),
                    "commentary": dimension.get("commentary", ""),
                    "run_dir": result_row.get("run_dir", ""),
                }
            )
    return rows


def judges_to_long_df(result_row: dict[str, Any], evaluations: list[Evaluation]):
    import pandas as pd

    return pd.DataFrame(judges_to_long_rows(result_row, evaluations))


def case_from_result_row(row: dict[str, Any]) -> dict[str, Any]:
    run_log = read_run_log(row.get("run_dir", ""))
    final_answer = str(run_log.get("final_answer", ""))
    calls = run_log.get("tool_calls", [])
    return {
        "id": row.get("id", ""),
        "repeat": row.get("repeat", ""),
        "question": row.get("question") or run_log.get("question", ""),
        "final_answer": final_answer,
        "sections": extract_sections(final_answer),
        "tool_calls": calls,
        "confidence": run_log.get("confidence", row.get("confidence")),
        "limitations": run_log.get("limitations", []),
        "run_dir": row.get("run_dir", ""),
    }


def read_run_log(run_dir: str | Path) -> dict[str, Any]:
    if not run_dir:
        return {}
    path = Path(run_dir) / "run_log.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def median_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        score = _float(row.get("score"))
        if score is None:
            continue
        grouped.setdefault(str(row.get("criterion", "")), []).append(score)
    return {criterion: {"score": statistics.median(values)} for criterion, values in grouped.items() if values}


def _judge_once(case: dict[str, Any], judge_model: str | None, judge_index: int) -> Evaluation:
    model = get_chat_model(model_id=judge_model, temperature=0.0, max_tokens=2048)
    structured = model.with_structured_output(Evaluation)
    content = _case_text(case, judge_index)
    result = structured.invoke([("system", EVAL_PROMPT), ("user", content)])
    if isinstance(result, Evaluation):
        return result
    return Evaluation.model_validate(result)


def _case_text(case: dict[str, Any], judge_index: int) -> str:
    calls = []
    for call in case.get("tool_calls", []):
        calls.append(
            {
                "tool": call.get("tool", ""),
                "args": call.get("args", ""),
                "observation": str(call.get("observation", ""))[:1200],
            }
        )
    payload = {
        "judge_index": judge_index,
        "question": case.get("question", ""),
        "confidence": case.get("confidence"),
        "limitations": case.get("limitations", []),
        "tool_calls": calls,
        "sections": case.get("sections", {}),
        "final_answer": case.get("final_answer", ""),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _failed_evaluation(reason: str) -> Evaluation:
    failed = Dimension(score=None, evidence="", commentary=f"Judge failed: {reason}")
    return Evaluation(
        framing=failed,
        coherence=failed,
        justification=failed,
        uncertainty=failed,
        metacognition=failed,
    )


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
