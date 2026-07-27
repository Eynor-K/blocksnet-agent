from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover — только для типов
    from blocksnet_agent import AgentResult


_STATUS_VALUES = {"supported", "refuted", "inconclusive"}
_SECTION_FALLBACK = {
    "analysis_plan": "ANALYSIS PLAN",
    "result": "RESULT",
}


# P1.1: контракт структурированного ответа. Терминальный инструмент ``submit_answer``
# (см. agent.py) собирает payload по этой схеме, MCP-слой отдаёт его как
# ``structuredContent``. ``recommendation_blocks``, ``measured_effects`` и
# ``hypotheses`` — машинно-читаемые поля, на которые подписываются downstream
# (MAS, иерархические агенты). Поле ``salvaged`` отделяет «агент успел вызвать
# ``submit_answer``» от «пост-процессинг восстановил ответ regex-парсером».


class MeasuredEffect(BaseModel):
    """P1.1: измеренный before→after по одному сервису.

    Не «сильное/слабое» по городу, а именно измеренный эффект конкретного
    вмешательства (compute_scenario_provision, propose_zone_development,
    экспериментальный what-if).
    """

    service_type: str
    strong_before: float | None = None
    strong_after: float | None = None
    missing_before: int | None = None
    missing_after: int | None = None
    full_before: int | None = None
    full_after: int | None = None
    partial_before: int | None = None
    partial_after: int | None = None
    source: str | None = None  # имя инструмента, которым измерено


class RecommendationItem(BaseModel):
    block_id: int
    service_type: str
    added_capacity: float | None = None
    rationale: str | None = None


class SubmittedAnswer(BaseModel):
    """P1.1: финальный структурированный ответ агента."""

    question: str
    analysis_plan: str = ""
    result: str = ""
    reflection: str = ""
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    measured_effects: list[MeasuredEffect] = Field(default_factory=list)
    confidence: float = 0.0
    limitations: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    run_id: str = ""
    city: str | None = None
    salvaged: bool = False  # True если восстановлено regex-парсером, не через submit_answer

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude_none=False)


def to_json(result: AgentResult) -> dict[str, Any]:
    """Convert BlocksNetAgent AgentResult to the MCP JSON contract.

    P1.1: если ``result['submitted_answer']`` задан (агент вызвал терминальный
    ``submit_answer``) — отдаём его как есть, в ``structuredContent`` MCP-вызов.
    Иначе — fallback с regex-парсингом и флагом ``salvaged=True``.
    """

    sections = dict(result.get("sections") or {})
    output = str(result.get("output") or "")
    run_dir = str(result.get("run_dir") or "")

    submitted = result.get("submitted_answer")
    if submitted is not None:
        # P1.1: структурный ответ — приоритетный путь. measured_effects /
        # recommendations приходят как dict'ы, а не regex-вытащенные числа.
        if not isinstance(submitted, dict):
            try:
                submitted = dict(submitted)
            except Exception:
                submitted = {}
        submitted.setdefault("run_id", _run_id(run_dir))
        submitted.setdefault("status", "ok")
        submitted["artifacts"] = submitted.get("artifacts") or _artifacts(run_dir)
        submitted.setdefault("salvaged", False)
        # P1.1: backward-compat — плоский список block_id из structured recommendations.
        if "recommendation_blocks" not in submitted:
            recs = submitted.get("recommendations") or []
            submitted["recommendation_blocks"] = [
                int(item.get("block_id"))
                for item in recs
                if isinstance(item, dict) and item.get("block_id") is not None
            ]
        # P1.2 fix: submitted-путь перезаписывал ``confidence`` самооценкой агента
        # (``agent передал в submit_answer(confidence=0.78)``), а авторитетная
        # P1.2-формула (взвешенная сумма сигналов) и basis терялись. Теперь:
        #   - ``confidence`` (число) — авторитетная P1.2-формула, если есть
        #     ``confidence_basis`` в ``result`` (агент её записал в state);
        #   - ``confidence_self`` — исходная самооценка агента для аудита;
        #   - ``confidence_basis`` — список сигналов, объясняющих значение.
        # Если basis нет (старые агенты или юнит-тесты) — оставляем submitted.confidence как есть.
        basis = result.get("confidence_basis")
        if basis:
            # P1.2 fix: сохранить самооценку ДО перезаписи, иначе потеряем.
            confidence_self = _as_float(submitted.get("confidence"), default=0.0)
            submitted["confidence"] = _as_float(result.get("confidence"), default=0.0)
            submitted["confidence_self"] = confidence_self
            submitted["confidence_basis"] = list(basis)
        # P-S5.3: финальный структурный синтез добавляется ВСЕГДА, не зависит от
        # того, был ли вызван ``submit_answer``. Сам submit даёт recommendation/
        # measured полезные для downstream, а синтез — для человека.
        _attach_synthesis(submitted, result)
        return submitted

    # P1.1: fallback — regex-парсинг прозы, помечаем salvaged=True, добавляем
    # SALVAGED_ANSWER в limitations, чтобы downstream видел «ответ восстановлен
    # постфактум, а не из структурного источника».
    result_text = _result_text(sections, output)

    # P1.6: если в state остался overlay-результат (агент не вызвал submit_answer,
    # но overlay_candidates отработал) — добавляем его как структурный
    # recommendations в fallback-путь. Это устраняет «пустой recommendation_blocks»
    # для случая, когда гипотезы-слои были, но агент не успел их submit'нуть.
    overlay_recommendations = result.get("overlay_recommendations") or []
    overlay_meta = result.get("overlay_meta") or {}

    # P0.5: валидация block_id против реального индекса кварталов города.
    # В salvage-пути регэксп вытаскивает числа из любого текста (REFLECTION,
    # гипотезы), включая «фантомные» ID вроде 6521 (транспортный квартал без
    # школ) или [0,1,2,3,4] (мусор из suggest_target_blocks). Если индекс есть —
    # оставляем только block_id, которые реально существуют в городе.
    valid_block_ids = result.get("valid_block_ids") or []
    valid_set = set(int(b) for b in valid_block_ids) if valid_block_ids else None

    payload = {
        "question": str(result.get("input") or ""),
        "analysis_plan": _section_text(sections, output, "ANALYSIS PLAN"),
        "result": result_text,
        "hypotheses": _parse_hypotheses(_section_text(sections, output, "HYPOTHESES")),
        "measured": _extract_measured(run_dir, result_text),
        "recommendation_blocks": _filter_valid_block_ids(
            _extract_recommendation_blocks(sections, output), valid_set
        ),
        "confidence": _as_float(result.get("confidence"), default=0.0),
        "limitations": _limitations(result),
        "artifacts": _artifacts(run_dir),
        "run_id": _run_id(run_dir),
        "salvaged": True,
    }
    if overlay_recommendations:
        # P1.6: предпочитаем overlay перед regex — это структурный источник.
        payload["recommendation_blocks"] = [
            int(item["block_id"])
            for item in overlay_recommendations
            if item.get("block_id") is not None
            and (valid_set is None or int(item["block_id"]) in valid_set)
        ]
        payload["overlay_candidates"] = overlay_recommendations
        payload["overlay_meta"] = overlay_meta
        # P1.6: overlay даёт «восстановленные из слоёв» рекомендации; не salvaged в строгом смысле.
        payload["salvaged"] = False
        payload["limitations"] = [
            lim for lim in payload["limitations"] if lim != "SALVAGED_ANSWER"
        ]
    if "SALVAGED_ANSWER" not in payload["limitations"]:
        payload["limitations"] = list(payload["limitations"]) + ["SALVAGED_ANSWER"]
    # P-S5.3: финальный структурный синтез прикладывается и в salvage-пути.
    _attach_synthesis(payload, result)
    return payload


def _section_text(sections: dict[str, str], output: str, name: str) -> str:
    text = str(sections.get(name) or "").strip()
    if text:
        return text
    match = re.search(
        rf"^{re.escape(name)}:\s*(.*?)(?=^[A-Z][A-Z \-]+:|\Z)",
        output or "",
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _result_text(sections: dict[str, str], output: str) -> str:
    result = _section_text(sections, output, "RESULT")
    reflection = _section_text(sections, output, "REFLECTION")
    if result and reflection:
        return f"{result}\n\nREFLECTION: {reflection}".strip()
    return result or output.strip()


def _parse_hypotheses(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line:
            continue
        fields = _parse_semicolon_fields(line)
        if not fields:
            continue
        status = fields.get("status", "inconclusive").strip().lower()
        if status not in _STATUS_VALUES:
            status = "inconclusive"
        item = {
            "id": fields.get("id", str(len(items) + 1)).strip(),
            "claim": fields.get("claim", "").strip(),
            "prediction": fields.get("prediction", "").strip(),
            "test": fields.get("test", "").strip(),
            "status": status,
            "evidence": fields.get("evidence", "").strip(),
        }
        if any(value for key, value in item.items() if key != "status"):
            items.append(item)
    return items


def _parse_semicolon_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    current_value: list[str] = []
    for part in line.split(";"):
        if ":" in part:
            if current_key:
                fields[current_key] = ";".join(current_value).strip()
            key, value = part.split(":", 1)
            current_key = key.strip().lower()
            current_value = [value.strip()]
        elif current_key:
            current_value.append(part.strip())
    if current_key:
        fields[current_key] = ";".join(current_value).strip()
    return fields


def _extract_measured(run_dir: str, result_text: str = "") -> dict[str, dict[str, float]]:
    measured = _service_before_after_values(result_text)
    if measured:
        return measured
    log = _read_run_log(run_dir)
    if not log:
        return {}
    text = "\n".join(str(call.get("observation", "")) for call in log.get("tool_calls", []))
    measured = _service_before_after_values(text)
    if measured:
        return measured
    service_match = re.search(
        r"\b([a-z][a-z0-9_]+)\s+(?:strong|missing)[_ ](?:before|after)\b",
        text,
        flags=re.IGNORECASE,
    )
    if service_match:
        values = _before_after_values(text)
        if values:
            measured[service_match.group(1)] = values
    if measured:
        return measured
    values = _before_after_values(text)
    return {"scenario": values} if values else {}


def _service_before_after_values(text: str) -> dict[str, dict[str, float]]:
    measured: dict[str, dict[str, float]] = {}
    pattern = re.compile(
        r"\b([a-z][a-z0-9_]+)\s+strong\s+(-?\d+(?:[.,]\d+)?)\s*(?:->|→)\s*(-?\d+(?:[.,]\d+)?)"
        r"(?:[^;\n.]*?\bmissing\s+(-?\d+(?:[.,]\d+)?)\s*(?:->|→)\s*(-?\d+(?:[.,]\d+)?))?",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text or ""):
        service = match.group(1)
        values = {
            "strong_before": float(match.group(2).replace(",", ".")),
            "strong_after": float(match.group(3).replace(",", ".")),
        }
        if match.group(4) is not None and match.group(5) is not None:
            values["missing_before"] = float(match.group(4).replace(",", "."))
            values["missing_after"] = float(match.group(5).replace(",", "."))
        measured[service] = values
    return measured


def _before_after_values(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    patterns = {
        "strong_before": r"strong[_ ]before\D+(-?\d+(?:[.,]\d+)?)",
        "strong_after": r"strong[_ ]after\D+(-?\d+(?:[.,]\d+)?)",
        "missing_before": r"missing[_ ]before\D+(-?\d+(?:[.,]\d+)?)",
        "missing_after": r"missing[_ ]after\D+(-?\d+(?:[.,]\d+)?)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            values[key] = float(match.group(1).replace(",", "."))
    arrows = re.findall(r"(-?\d+(?:[.,]\d+)?)\s*(?:->|→)\s*(-?\d+(?:[.,]\d+)?)", text)
    if arrows and "strong_before" not in values and "strong_after" not in values:
        before, after = arrows[-1]
        values["strong_before"] = float(before.replace(",", "."))
        values["strong_after"] = float(after.replace(",", "."))
    return values


def _extract_recommendation_blocks(sections: dict[str, str], output: str) -> list[int]:
    text = " ".join(str(sections.get(name, "")) for name in ("RESULT", "REFLECTION", "HYPOTHESES"))
    if not text.strip():
        text = output
    result: list[int] = []
    for bracketed in re.findall(r"(?:квартал\w*|blocks?)\D{0,80}\[([0-9,\s]+)\]", text, flags=re.IGNORECASE):
        for raw in re.findall(r"\d{1,5}", bracketed):
            value = int(raw)
            if value not in result:
                result.append(value)
    found = re.findall(r"(?:block(?:_id)?|кварт\w*)\s*№?\s*(\d{1,5})", text, flags=re.IGNORECASE)
    for raw in found:
        value = int(raw)
        if value not in result:
            result.append(value)
    return result


def _filter_valid_block_ids(
    block_ids: list[int], valid_set: set[int] | None
) -> list[int]:
    """P0.5: оставить только block_id, реально существующие в индексе города.

    Если ``valid_set`` is None (город не загружен или в юнит-тестах) — пропускаем
    как есть, чтобы не сломать совместимость.
    """
    if valid_set is None:
        return list(block_ids)
    return [int(b) for b in block_ids if int(b) in valid_set]


def _limitations(result: AgentResult) -> list[str]:
    values = result.get("limitations") or []
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values if str(value).strip()]


def _artifacts(run_dir: str) -> list[str]:
    log = _read_run_log(run_dir)
    if log:
        files = []
        base = Path(run_dir)
        for item in log.get("saved_files", []):
            path = Path(str(item.get("path", "")))
            files.append(_relative_or_name(path, base))
        if files:
            return files
    path = Path(run_dir) if run_dir else None
    if not path or not path.exists():
        return []
    artifacts = [
        _relative_or_name(item, path)
        for item in path.rglob("*")
        if item.is_file() and item.name not in {"run_log.json", "run_log.md"}
    ]
    return sorted(artifacts)


def _relative_or_name(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


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


def _run_id(run_dir: str) -> str:
    if not run_dir:
        return ""
    name = Path(run_dir).name
    return name.removeprefix("run_")


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _attach_synthesis(payload: dict[str, Any], result: AgentResult) -> None:
    """P-S5.3: приложить структурный финальный синтез к payload.

    ``result["synthesis"]`` — ``FinalSynthesis`` (или None). ``synthesis_path``
    и ``fallback_used`` приходят из ``result["synthesis_path"]`` и
    ``result["synthesis"].fallback_used``. Старые payload'ы (без синтеза)
    остаются совместимыми — ключи добавлены с default-пустыми значениями.
    """
    syn = result.get("synthesis")
    path = result.get("synthesis_path") or ""
    if syn is None:
        # Если по какой-то причине синтез не выполнен — оставляем пустые
        # ключи, чтобы контракт не «плавал» между вызовами.
        payload.setdefault("synthesis", "")
        payload.setdefault("synthesis_citations", [])
        payload.setdefault("synthesis_path", "")
        payload.setdefault("synthesis_fallback", False)
        return
    # ``syn`` — FinalSynthesis-dataclass.
    markdown = getattr(syn, "to_markdown", lambda: "")()
    citations = list(getattr(syn, "citations", []) or [])
    fallback_used = bool(getattr(syn, "fallback_used", False))
    payload["synthesis"] = markdown
    payload["synthesis_citations"] = citations
    payload["synthesis_path"] = str(path) if path else ""
    payload["synthesis_fallback"] = fallback_used
