from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


# P1.6: жёсткие слои (CSP) и мягкие слои (MCDA). ``hard`` — отсекающая маска:
# блок, не прошедший все hard-слои, исключается из кандидатов. ``soft`` — взвешенный
# вклад в итоговый score: ``Σ wᵢ · scoreᵢ`` по выжившим. ``mask`` — спецслучай
# hard-слоя, отрезающий кварталы с условием (population=0, land_use=...).
HYPOTHESIS_KIND_HARD = "hard"
HYPOTHESIS_KIND_SOFT = "soft"
HYPOTHESIS_DIRECTIONS = ("below", "above", "mask")
HYPOTHESIS_KINDS = (HYPOTHESIS_KIND_HARD, HYPOTHESIS_KIND_SOFT)


@dataclass
class Hypothesis:
    id: str
    claim: str
    prediction: str
    test: str
    status: str = "open"
    parent_id: str | None = None
    evidence: str = ""
    # P1.6: вес и тип гипотезы для слоевой модели. ``kind`` и ``weight`` —
    # по умолчанию сохранены backward-compat (kind=soft, weight=1.0).
    kind: str = HYPOTHESIS_KIND_SOFT
    weight: float = 1.0
    result_key: str = ""
    column: str = ""
    direction: str = "below"  # below | above | mask

    def complete(self) -> bool:
        return bool(self.claim.strip() and self.prediction.strip() and self.test.strip())

    def is_layer(self) -> bool:
        """P1.6: гипотеза пригодна для накладываемого слоя, если задан ``result_key``.

        Без ``result_key`` гипотеза остаётся «нарративной» (как в P0.x) и не
        участвует в ``overlay_candidates``.
        """
        return bool(self.result_key)


@dataclass
class HypothesisLedger:
    hypotheses: list[Hypothesis] = field(default_factory=list)

    def layers(self) -> list["Hypothesis"]:
        """P1.6: только гипотезы-слои (с заданным ``result_key``) — кандидаты для overlay."""
        return [item for item in self.hypotheses if item.is_layer()]

    def hard_layers(self) -> list["Hypothesis"]:
        return [item for item in self.layers() if item.kind == HYPOTHESIS_KIND_HARD]

    def soft_layers(self) -> list["Hypothesis"]:
        return [item for item in self.layers() if item.kind == HYPOTHESIS_KIND_SOFT]

    def to_context(self) -> str:
        if not self.hypotheses:
            return ""
        lines = [
            "PTR hypothesis ledger (generated before tool calls; use as research orientation, not a fixed workflow):"
        ]
        for item in self.hypotheses:
            lines.append(
                f"- {item.id}: claim={item.claim}; prediction={item.prediction}; "
                f"candidate_test={item.test}; status={item.status}"
            )
        return "\n".join(lines)

    def to_section(self) -> str:
        if not self.hypotheses:
            return ""
        lines = []
        for item in self.hypotheses:
            parent = f"; parent_id: {item.parent_id}" if item.parent_id else ""
            evidence = f"; evidence: {item.evidence}" if item.evidence else ""
            # P1.6: kind/weight в to_section, чтобы было видно «слой это или нет».
            layer_meta = ""
            if item.is_layer():
                layer_meta = f"; kind={item.kind}; weight={item.weight}; result_key={item.result_key}; column={item.column or '*'}; direction={item.direction}"
            lines.append(
                f"- id: {item.id}; claim: {item.claim}; prediction: {item.prediction}; "
                f"test: {item.test}; status: {item.status}{parent}{evidence}{layer_meta}"
            )
        return "\n".join(lines)

    def to_jsonable(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.hypotheses]


def build_hypothesis_ledger(
    task: str,
    tool_names: list[str],
    llm_invoke,
    available_metrics: list[str] | None = None,
) -> HypothesisLedger:
    """Fail-open ex-ante hypothesis generation."""
    metrics_hint = ", ".join(available_metrics or [])
    prompt = (
        "Сформируй 2-5 фальсифицируемых гипотез для BlocksNetAgent ДО вызова инструментов.\n"
        "Это ориентир исследования, не workflow. Для каждой гипотезы дай claim, prediction и candidate test tool.\n"
        "Prediction ОБЯЗАН быть операционализируемым доступным инструментом: укажи result_key/metric, "
        "сущность (block_id N — N это ПЛЕЙСХОЛДЕР, подставь реальный) и проверяемый ориентир: "
        "'= 0', '< median', '> median' или конкретный порог.\n"
        "Хороший формат: \"competitive_provision_<service> for block_id <N> < median\" или "
        "\"scenario_provision for block_id <N> improves strong provision after compute_scenario_provision\".\n"
        "ВАЖНО про сущности: подставляй ТОЛЬКО block_id, явно названный В ВОПРОСЕ. Если вопрос НЕ называет "
        "конкретный квартал (городской/размещение/диагностика) — НЕ выдумывай номер: формулируй предсказание "
        "о кандидатных кварталах, которые надо НАЙТИ (через suggest_target_blocks), или о городской метрике, "
        "а не о произвольном block_id. Не подставляй номер из примера.\n"
        "Не используй непроверяемые формулировки вроде 'на 20%', 'лучше соседних кварталов', если такой "
        "ориентир не вычисляется доступным инструментом.\n"
        "Используй только инструменты из списка. Верни строго JSON-массив объектов с ключами "
        "id, claim, prediction, test. Не добавляй markdown.\n\n"
        f"QUESTION: {task}\n\nTOOLS: {', '.join(tool_names[:80])}\n\n"
        f"AVAILABLE_RESULT_KEYS_OR_METRICS: {metrics_hint or 'none yet; prefer tools that create measurable result_keys'}"
    )
    try:
        response = llm_invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        data = _extract_json_array(content)
    except Exception:
        return HypothesisLedger()
    hypotheses = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        hyp = Hypothesis(
            id=str(item.get("id") or f"H{index}"),
            claim=str(item.get("claim", "")).strip(),
            prediction=str(item.get("prediction", "")).strip(),
            test=str(item.get("test", "")).strip(),
        )
        if hyp.complete():
            hypotheses.append(hyp)
    return HypothesisLedger(hypotheses[:5])


def classify_hypothesis_ledger(
    ledger: HypothesisLedger,
    steps: list[dict[str, str]],
    llm_invoke,
    state: dict[str, Any] | None = None,
) -> HypothesisLedger:
    if not ledger.hypotheses:
        return ledger
    evidence = _evidence_text(steps)
    if not evidence:
        for item in ledger.hypotheses:
            item.status = "inconclusive"
            item.evidence = "no successful tool evidence"
        return ledger
    for item in ledger.hypotheses:
        if item.test and not _test_was_called(item.test, steps):
            item.status = "inconclusive"
            item.evidence = f"candidate test '{item.test}' was not called"
            continue
        metric = _classify_metric_prediction(item.prediction, evidence, state or {})
        if metric:
            item.status, item.evidence = metric
            continue
        # P1.3: передаём state в _classify_numeric_prediction, чтобы адресный
        # путь (``state[result_key]``) имел приоритет над «numbers[-1] из прозы».
        numeric = _classify_numeric_prediction(item.prediction, evidence, state or {})
        if numeric:
            item.status, item.evidence = numeric
            continue
        delta = _classify_delta_prediction(item.prediction, evidence)
        if delta:
            item.status, item.evidence = delta
            continue
        qualitative = _classify_qualitative(item, evidence, llm_invoke)
        if qualitative:
            item.status, item.evidence = qualitative
        else:
            item.status = "inconclusive"
            item.evidence = "prediction could not be compared to observations"
    return ledger


def inconclusive_measurement_issue(
    ledger: HypothesisLedger,
    tool_names: set[str],
    steps: list[dict[str, str]],
) -> str:
    for item in ledger.hypotheses:
        if item.status != "inconclusive":
            continue
        test = _normalize_tool_name(item.test, tool_names)
        if test and not _tool_was_called(test, steps):
            return (
                f"гипотеза {item.id} осталась inconclusive, хотя её test '{test}' доступен и не был вызван — "
                "измерь эту гипотезу инструментом или явно объясни, почему измерить реально нечем"
            )
    return ""


def hypothesis_contradiction_issue(ledger: HypothesisLedger, output_text: str) -> str:
    refuted_claims = [item.claim for item in ledger.hypotheses if item.status == "refuted"]
    if not refuted_claims:
        return ""
    text = output_text.lower()
    for claim in refuted_claims:
        words = [word for word in re.split(r"\W+", claim.lower()) if len(word) > 4]
        if words and sum(1 for word in words if word in text) >= max(2, len(words) // 2):
            return (
                "гипотеза в PTR-леджере получила status=refuted, но финальный ответ всё ещё "
                "утверждает её claim — отклони или переформулируй гипотезу и объясни наблюдение"
            )
    return ""


def merge_hypotheses_section(output_text: str, ledger: HypothesisLedger) -> str:
    section = ledger.to_section()
    if not section:
        return output_text
    pattern = re.compile(
        r"^HYPOTHESES:.*?(?=^(?:ANALYSIS PLAN|RESULT|REFLECTION|NUMERIC SELF-CHECK|FOLLOW_UPS|CONFIDENCE|LIMITATIONS):|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(output_text or ""):
        return pattern.sub(f"HYPOTHESES: {section}\n", output_text)
    return (output_text.rstrip() + f"\nHYPOTHESES: {section}").strip()


# --- P1.6: накладывающиеся слои (CSP + weighted-overlay) ---------------------------
#
# Модель:
# 1. Каждая гипотеза-сной (``is_layer()``) имеет ``kind="hard" | "soft"``,
#    ``result_key``, ``column``, ``direction``.
# 2. ``overlay_candidates(ledger, state)``:
#    a) Применяет hard-слои как маски (AND). Кварталы, не прошедшие хоть одну
#       жёсткую маску, исключаются (CSP — отсечение домена).
#    b) К выжившим применяет soft-слои как взвешенный вклад:
#       ``score_block = Σ w_i · s_i(block)``, Σ w_i = 1.
#    c) Возвращает dict ``{block_id: {score, layers_passed, ...}}``, отсортированный
#       по убыванию score.
# 3. ``overlay_candidates`` — авторитетный источник ``recommendations`` для P1.1.
#    Агент может вызвать ``submit_answer`` с ``recommendations`` из overlay-результата
#    — и тогда ``to_json`` отдаст их структурно (без regex-парсинга).


def _overlay_score_for_block(value: float | None, direction: str) -> float:
    """P1.6: нормализация значения в 0..1 по направлению слоя.

    ``below`` → меньше = лучше; ``above`` → больше = лучше; ``mask`` → 1.0 если прошёл,
    иначе вызывающий код не должен пускать блок. Для weighted-overlay используем
    само значение в диапазоне [0, 1] (типичный случай — provision уже в 0..1);
    для непрерывных значений выше 1 (например population) — нужно нормировать на
    медиану/макс вне функции.
    """
    if value is None:
        return 0.0
    v = float(value)
    if direction == "below":
        return max(0.0, min(1.0, 1.0 - v))  # v=0 → 1.0 (лучший), v=1 → 0.0
    if direction == "above":
        return max(0.0, min(1.0, v))  # v=0 → 0.0, v=1 → 1.0
    # mask: вызывающий код обрабатывает отдельно
    return 0.0


def overlay_candidates(
    ledger: HypothesisLedger,
    state: dict,
    top_n: int = 10,
) -> dict[str, Any]:
    """P1.6: наложение слоёв — CSP (hard) + MCDA (soft) — и выдача top-N кандидатов.

    Args:
        ledger: ``HypothesisLedger`` с гипотезами-слоями (поля ``result_key``,
            ``column``, ``kind``, ``weight``, ``direction``).
        state: agent state — здесь лежат поквартальные значения ``result_key``
            (например, ``competitive_provision_school``).
        top_n: сколько top-кандидатов вернуть.

    Returns:
        ``{
            "candidates": [{"block_id": int, "score": float, "layers_passed": int, "layers_total": int}],
            "hard_passed": int,  # сколько блоков прошло ВСЕ hard-слои
            "hard_total": int,
            "diagnostic_layers": int,  # hard-слои, отсекшие хотя бы один блок
            "nondiagnostic_layers": int,
        }``

    Без слоёв возвращает ``{"candidates": [], "hard_passed": 0, ...}``.
    """
    layers = ledger.layers()
    if not layers:
        return {
            "candidates": [],
            "hard_passed": 0,
            "hard_total": 0,
            "diagnostic_layers": 0,
            "nondiagnostic_layers": 0,
        }
    hard = [layer for layer in layers if layer.kind == HYPOTHESIS_KIND_HARD]
    soft = [layer for layer in layers if layer.kind == HYPOTHESIS_KIND_SOFT]
    diag_hard = 0
    nondiag_hard = 0

    # P1.6: собираем множество индексов = все блоки, упомянутые хотя бы в одном
    # из кэшированных ``result_key``. Если кэш пуст — overlay нечего оценивать.
    indexes: set = set()
    series_per_layer: dict[str, Any] = {}
    for layer in layers:
        if not layer.result_key or layer.result_key not in state:
            continue
        from blocksnet_agent.tools.data import _metric_series_for_blocks

        series = _metric_series_for_blocks(state[layer.result_key], column=layer.column or None)
        if series is None or series.empty:
            continue
        series_per_layer[layer.id] = series
        indexes.update(series.index.tolist())

    if not indexes:
        return {
            "candidates": [],
            "hard_passed": 0,
            "hard_total": len(hard),
            "diagnostic_layers": 0,
            "nondiagnostic_layers": len(hard),
        }

    # P1.6: применяем hard-слои как маски (CSP). Каждый hard-слой отрезает домен;
    # если он не отрезал ничего (все блоки прошли) — он «недиагностичный».
    survivors = set(indexes)
    for layer in hard:
        if layer.id not in series_per_layer:
            # hard-слой без данных = не можем применить; пропускаем как «мягкий»,
            # т.е. никого не отсекает, но и не вносит вклад.
            nondiag_hard += 1
            continue
        series = series_per_layer[layer.id]
        if layer.direction == "mask":
            # mask: оставляем блоки со значением != 0 (или != default).
            threshold = 0.0
            before = len(survivors)
            survivors = {bid for bid in survivors if series.get(bid, 0) != threshold}
            if len(survivors) < before:
                diag_hard += 1
            else:
                nondiag_hard += 1
        else:
            # below/above: блок «проходит», если значение хуже медианы (для
            # задачи размещения сервиса — ищем дефицит).
            median = float(series.median())
            before = len(survivors)
            if layer.direction == "below":
                survivors = {bid for bid in survivors if float(series.get(bid, median)) < median}
            else:
                survivors = {bid for bid in survivors if float(series.get(bid, median)) > median}
            if len(survivors) < before:
                diag_hard += 1
            else:
                nondiag_hard += 1

    # P1.6: взвешенный overlay по soft-слоям для выживших.
    weight_sum = sum(layer.weight for layer in soft)
    weight_sum = float(weight_sum) if weight_sum > 0 else 1.0
    scores: dict[int, float] = {bid: 0.0 for bid in survivors}
    for layer in soft:
        if layer.id not in series_per_layer:
            continue
        series = series_per_layer[layer.id]
        norm_weight = float(layer.weight) / weight_sum
        for bid in list(scores.keys()):
            value = series.get(bid)
            scores[bid] += norm_weight * _overlay_score_for_block(value, layer.direction)

    # P1.6: ранжируем по score, режем top_n.
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    candidates = [
        {
            "block_id": int(bid),
            "score": float(score),
            "layers_passed": len(hard) + len(soft),
            "layers_total": len(layers),
        }
        for bid, score in ranked[: max(0, int(top_n))]
    ]
    return {
        "candidates": candidates,
        "hard_passed": len(survivors),
        "hard_total": len(hard),
        "diagnostic_layers": diag_hard,
        "nondiagnostic_layers": nondiag_hard,
    }


def _extract_json_array(content: str) -> list[Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    return data if isinstance(data, list) else []


def _evidence_text(steps: list[dict[str, str]]) -> str:
    lines = []
    for step in steps:
        obs = str(step.get("observation", ""))
        if not obs or obs.startswith(("Ошибка:", "Traceback", "Exception")):
            continue
        lines.append(f"{step.get('tool')}: {obs}")
    return "\n".join(lines)[:8000]


def _test_was_called(test: str, steps: list[dict[str, str]]) -> bool:
    """P1.3: точное сравнение имени tool, не substring-матч.

    Раньше: ``tool_name.lower() in test.lower()`` — ложно срабатывал на похожих
    суффиксах (например, ``compute_service_provision`` vs ``get_service_provision``)
    или наоборот — ``test.lower() in tool_name.lower()`` — ложно подбирал
    ``"foo" in "barfoo"``. Теперь — строгое равенство после normalize.
    """
    test_lower = (test or "").lower().strip()
    if not test_lower:
        return False
    for step in steps:
        tool = str(step.get("tool", "")).lower().strip()
        if not tool:
            continue
        if tool == test_lower:
            return True
    return False


def _tool_was_called(tool: str, steps: list[dict[str, str]]) -> bool:
    return any(str(step.get("tool", "")) == tool for step in steps)


def _normalize_tool_name(test: str, tool_names: set[str]) -> str:
    lowered = str(test or "").lower()
    for name in tool_names:
        if name.lower() == lowered or name.lower() in lowered:
            return name
    return ""


def _classify_metric_prediction(
    prediction: str,
    evidence: str,
    state: dict[str, Any],
) -> tuple[str, str] | None:
    pred = prediction.strip()
    result_key = _prediction_result_key(pred, state)
    block_id = _prediction_block_id(pred)
    if result_key and block_id is not None and result_key in state:
        try:
            from blocksnet_agent.tools.data import _metric_series_for_blocks

            series = _metric_series_for_blocks(state[result_key])
            if series is not None and not series.empty and block_id in series.index:
                value = float(series.loc[block_id])
                return _compare_value_to_prediction(value, float(series.median()), pred, f"{result_key} block_id {block_id}")
        except Exception:
            pass
    parsed = _metric_value_from_evidence(pred, evidence)
    if parsed:
        value, median, label = parsed
        return _compare_value_to_prediction(value, median, pred, label)
    return None


def _prediction_result_key(prediction: str, state: dict[str, Any]) -> str:
    candidates = sorted((str(key) for key in state if key not in {"blocks", "acc_mx"}), key=len, reverse=True)
    lowered = prediction.lower()
    for key in candidates:
        if key.lower() in lowered:
            return key
    match = re.search(r"\b(?:result_key|metric)\s*[:=]\s*([a-z][a-z0-9_]+)", lowered)
    return match.group(1) if match else ""


def _prediction_block_id(prediction: str) -> int | None:
    match = re.search(r"(?:block(?:_id)?|кварт\w*)\s*№?\s*(\d{1,5})", prediction, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _metric_value_from_evidence(prediction: str, evidence: str) -> tuple[float, float, str] | None:
    result_key = re.search(r"\b[a-z][a-z0-9_]*(?:provision|indicators|accessibility|centrality|diversity)[a-z0-9_]*\b", prediction)
    block_id = _prediction_block_id(prediction)
    if not result_key or block_id is None:
        return None
    key = result_key.group(0)
    for line in evidence.splitlines():
        if key.lower() not in line.lower() or f"block_id {block_id}" not in line.lower():
            continue
        tail = line.lower().split(f"block_id {block_id}", 1)[1]
        value_match = re.search(r":\s*([-+]?\d+(?:[.,]\d+)?)", tail)
        median_match = re.search(r"медиана города\s+([-+]?\d+(?:[.,]\d+)?)", line, flags=re.IGNORECASE)
        if value_match and median_match:
            return (
                float(value_match.group(1).replace(",", ".")),
                float(median_match.group(1).replace(",", ".")),
                f"{key} block_id {block_id} from evidence",
            )
        numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", tail)
        if len(numbers) >= 2:
            return (
                float(numbers[0].replace(",", ".")),
                float(numbers[1].replace(",", ".")),
                f"{key} block_id {block_id} from evidence",
            )
    return None


def _compare_value_to_prediction(value: float, median: float, prediction: str, label: str) -> tuple[str, str] | None:
    pred = prediction.lower().replace(",", ".")
    threshold_match = re.search(r"(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)", pred)
    if threshold_match:
        op = threshold_match.group(1)
        threshold = float(threshold_match.group(2))
        supported = {
            ">": value > threshold,
            ">=": value >= threshold,
            "<": value < threshold,
            "<=": value <= threshold,
            "=": abs(value - threshold) <= 1e-9,
        }[op]
        status = "supported" if supported else "refuted"
        return status, f"{label}: observed {value:.4f}; prediction {op} {threshold:.4f}"
    if any(marker in pred for marker in ("ниже медиан", "below median", "< median", "less than median")):
        status = "supported" if value < median else "refuted"
        return status, f"{label}: observed {value:.4f}, city median {median:.4f}; expected below median"
    if any(marker in pred for marker in ("выше медиан", "above median", "> median", "greater than median")):
        status = "supported" if value > median else "refuted"
        return status, f"{label}: observed {value:.4f}, city median {median:.4f}; expected above median"
    if any(marker in pred for marker in ("= median", "равно медиан")):
        status = "supported" if abs(value - median) <= 1e-9 else "refuted"
        return status, f"{label}: observed {value:.4f}, city median {median:.4f}; expected equal median"
    return None


def _classify_numeric_prediction(
    prediction: str,
    evidence: str,
    state: dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    r"""P1.3: верификация — по адресной метрике из ``state``, не по ``numbers[-1]``.

        Раньше: ``observed = numbers[-1]`` — бралось последнее число из обрезанной
        витрины ``evidence`` (например, ``0.130794`` из таблицы на 100 строк).
        Это давало ложные вердикты вроде ``0.130794 >= 3 → refuted``.

        Теперь:
          1. Если ``state`` задан и в нём есть ``result_key`` + ``block_id`` — берём
             значение из ``state[result_key]`` (тот же путь, что и ``overlay_candidates``
             в P1.6). Это и есть «адресная метрика» — истина из расчётного кэша.
          2. Иначе — fallback по evidence, но НЕ ``numbers[-1]``: ищем первое
             положительное число из конкретной строки, относящейся к ``block_id``
             из prediction, чтобы не ловить «хвост» больших таблиц.
          3. ``block_id=<N>`` в prediction НЕ интерпретируется как порог — для порога
             ищем оператор ``(>=|<=|>|<|=)`` ЗА пределами выражения
             ``block_id\s*=?`` ``\s*\d+``.
        """
    pred = prediction.replace(",", ".")
    # P1.3: сначала пытаемся адресный путь — state[result_key] для конкретного
    # ``block_id`` из prediction. Это истина из расчётного кэша, не из прозы.
    if state:
        try:
            result_key = _prediction_result_key(prediction, state)
            block_id = _prediction_block_id(prediction)
            if result_key and block_id is not None and result_key in state:
                from blocksnet_agent.tools.data import _metric_series_for_blocks

                series = _metric_series_for_blocks(state[result_key])
                if series is not None and not series.empty and block_id in series.index:
                    value = float(series.loc[block_id])
                    return _compare_value_to_prediction(
                        value,
                        float(series.median()),
                        pred,
                        f"{result_key} block_id {block_id} from state",
                    )
        except Exception:
            pass

    # P1.3: фильтруем threshold-regex так, чтобы ``block_id 42`` не попало в порог.
    # Ищем оператор, причём слева от него — НЕ ``block_id=<N>``.
    threshold_match = _extract_threshold_operator(pred)
    if not threshold_match:
        return None
    op, threshold = threshold_match

    # P1.3: ищем число в evidence, привязанное к ``block_id`` из prediction.
    # Если в evidence ничего привязанного нет — inconclusive (НЕ numbers[-1]).
    block_id = _prediction_block_id(prediction)
    observed = _observed_value_for_block(evidence, block_id) if block_id is not None else None
    if observed is None:
        # P1.3: «нет конкретного наблюдения, привязанного к block_id» —
        # вернуть inconclusive, а не «всё подтверждено по последнему числу».
        return (
            "inconclusive",
            f"numeric threshold {op} {threshold:g} found, but no observation tied to block_id {block_id}",
        )

    supported = {
        ">": observed > threshold,
        ">=": observed >= threshold,
        "<": observed < threshold,
        "<=": observed <= threshold,
    }[op]
    status = "supported" if supported else "refuted"
    return status, f"numeric comparison: observed {observed:g} {op} expected threshold {threshold:g}"


# P1.3: выделение оператора сравнения из prediction, с защитой от ложного
# срабатывания на ``block_id=42``. Ищем оператор, перед которым НЕ стоит
# ``block_id``/``кварт``/``block`` (с номером) — это и есть валидный threshold.
# Только строгие/нестрогие неравенства: ``=`` исключён (это равенство, не
# порог, и именно ``=`` в ``block_id=42`` — главный источник ложных срабатываний).
_THRESHOLD_OPS = (">=", "<=", ">", "<")
_BLOCK_PREFIX_RE = re.compile(
    r"\b(?:block[_\s-]?id|кварт\w*|block)\s*[=№:]?\s*\d+",
    flags=re.IGNORECASE,
)


def _extract_threshold_operator(prediction: str) -> tuple[str, float] | None:
    """P1.3: найти первый оператор сравнения, НЕ внутри ``block_id N``.

    Игнорируем все вхождения оператора, которые являются частью выражения
    ``block_id[=\s]*\d+``. Например, в ``block_id=42 provision > 0.3``:
      - ``=42`` — это часть block_id (пропускаем),
      - ``> 0.3`` — это валидный threshold (возвращаем).
    """
    candidates: list[tuple[int, str, float]] = []
    for op in _THRESHOLD_OPS:
        for match in re.finditer(re.escape(op) + r"\s*(-?\d+(?:\.\d+)?)", prediction):
            try:
                threshold = float(match.group(1))
            except ValueError:
                continue
            candidates.append((match.start(), op, threshold))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    for start, op, threshold in candidates:
        # P1.3: пропускаем кандидатов, которые идут сразу за ``block_id N``
        # (включая компактную форму ``block_id=42``).
        prefix_match = _BLOCK_PREFIX_RE.match(prediction, endpos=start)
        if prefix_match and prefix_match.end() >= start - 1:
            # Оператор стоит сразу за ``block_id N`` (или между N и оп. — только пробелы).
            tail = prediction[prefix_match.end():start]
            if not tail.strip(" \t"):
                # Сразу ``block_id N<op>`` — ложное срабатывание.
                continue
        return op, threshold
    return None


def _observed_value_for_block(evidence: str, block_id: int) -> float | None:
    """P1.3: первое числовое значение в evidence, привязанное к ``block_id``.

    До этого был ``numbers[-1]`` — последнее число во всём evidence, что для
    длинного табличного вывода давало «хвост» колонки (0.130794 в случае
    из аудита). Теперь ищем строку с упоминанием ``block_id N`` и берём
    первое положительное число ПОСЛЕ упоминания ``block_id N`` — то, что
    относится именно к нашему блоку (а не сам N, не «=»).
    """
    if not evidence:
        return None
    needles = [
        f"block_id {block_id} ",
        f"block_id={block_id} ",
        f"block_id {block_id},",
        f"block_id {block_id}\n",
        f"block_id {block_id}\t",
    ]
    for line in evidence.splitlines():
        low = line.lower()
        # Находим позицию упоминания block_id в строке.
        bid_positions: list[int] = []
        for needle in needles:
            idx = low.find(needle.lower())
            if idx >= 0:
                # Сдвиг за needle (включая пробел после N).
                bid_positions.append(idx + len(needle))
        # Без пробела после N — ``block_id 42:`` / ``block_id 42: provision=0.5``.
        compact_pos = low.find(f"block_id {block_id}:")
        if compact_pos >= 0:
            bid_positions.append(compact_pos + len(f"block_id {block_id}:"))
        compact_eq = low.find(f"block_id={block_id}:")
        if compact_eq >= 0:
            bid_positions.append(compact_eq + len(f"block_id={block_id}:"))
        if not bid_positions:
            continue
        # Берём самое раннее упоминание и ищем первое положительное число ПОСЛЕ него.
        start = min(bid_positions)
        tail = line[start:]
        numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", tail)
        for raw in numbers:
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                continue
            if value > 0:  # пропускаем 0, отрицательные как «нет измерения»
                return value
    return None


def _classify_delta_prediction(prediction: str, evidence: str) -> tuple[str, str] | None:
    pred = prediction.lower()
    wants_improve = any(marker in pred for marker in ("improve", "increase", "улучш", "повыс", "увелич"))
    wants_reduce = any(marker in pred for marker in ("reduce", "decrease", "сниж", "уменьш"))
    if not (wants_improve or wants_reduce):
        return None
    pairs = [
        (float(a.replace(",", ".")), float(b.replace(",", ".")))
        for a, b in re.findall(r"(-?\d+(?:[.,]\d+)?)\s*(?:->|→)\s*(-?\d+(?:[.,]\d+)?)", evidence)
    ]
    if not pairs:
        return None
    if wants_improve:
        supported = any(after > before for before, after in pairs)
        status = "supported" if supported else "refuted"
        return status, "before→after comparison: " + "; ".join(f"{a:g}->{b:g}" for a, b in pairs[:6])
    if wants_reduce:
        supported = any(after < before for before, after in pairs)
        status = "supported" if supported else "refuted"
        return status, "before→after comparison: " + "; ".join(f"{a:g}->{b:g}" for a, b in pairs[:6])
    return None


def _classify_qualitative(item: Hypothesis, evidence: str, llm_invoke) -> tuple[str, str] | None:
    prompt = (
        "Classify one hypothesis strictly against tool observations.\n"
        "Allowed status: supported, refuted, inconclusive. Return one line as JSON object "
        "{\"status\":\"...\",\"evidence\":\"short reason\"}.\n\n"
        f"CLAIM: {item.claim}\nPREDICTION: {item.prediction}\nTEST: {item.test}\n\nOBSERVATIONS:\n{evidence}"
    )
    try:
        response = llm_invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        data = json.loads(content.strip())
        status = str(data.get("status", "")).strip().lower()
        if status not in {"supported", "refuted", "inconclusive"}:
            return None
        return status, str(data.get("evidence", "")).strip()[:500]
    except Exception:
        return None
