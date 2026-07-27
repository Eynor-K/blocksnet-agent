from __future__ import annotations

import hashlib
from difflib import SequenceMatcher, get_close_matches

import pandas as pd
from langchain_core.tools import tool
from blocksnet.analysis.provision import competitive_provision, provision_strong_total, provision_weak_total, shared_provision
from blocksnet.config.service_types.config import SERVICE_TYPES
from blocksnet.enums import LandUse

from blocksnet_agent.runtime import record_file
from blocksnet_agent.tools.data import ensure_acc_mx, ensure_blocks
from blocksnet_agent.tools.demand import block_demand_proxy
from blocksnet_agent.tools.optimize import _SERVICE_PRESETS
from blocksnet_agent.tools.viz import save_metric_map


# P0.1: жёсткий лимит LP-пересчётов за один запуск. Свыше лимита кэш не спасает —
# инструмент возвращает честное ``STOP`` без нового LP, чтобы не уходить в 10-минутный таймаут.
# Лимит подобран эмпирически под СПб (9368 кварталов, ~25-40 сек на LP): 8 — это
# исчерпывающий пакет 6-8 ключевых сервисов, чего хватает для большинства вопросов
# без риска таймаута MCP-клиента (см. run 20260709-120825, упавший на 8-м LP).
# P0.5: можно переопределить через env BLOCKSNET_LP_BUDGET для отладки/регрессий.
import os as _os
_DEFAULT_LP_BUDGET = 8
_LP_BUDGET = int(_os.environ.get("BLOCKSNET_LP_BUDGET", _DEFAULT_LP_BUDGET))
_LP_STATE_KEY = "_lp_count"


def _lp_budget_exceeded(state: dict) -> bool:
    return int(state.get(_LP_STATE_KEY, 0)) >= _LP_BUDGET


def _register_lp(state: dict) -> int:
    count = int(state.get(_LP_STATE_KEY, 0)) + 1
    state[_LP_STATE_KEY] = count
    return count


def _content_hash(value) -> str:
    """P0.1: стабильный хеш содержимого DataFrame/Series для ключа provision-кэша.

    Берём только ``index`` + значения — не геометрию и не служебные колонки,
    чтобы хеш действительно отражал «нагрузку» на LP, а не менялся из-за метаданных.
    """
    try:
        if isinstance(value, pd.DataFrame):
            payload = value.to_numpy()
            index = list(value.index)
        elif isinstance(value, pd.Series):
            payload = value.to_numpy()
            index = list(value.index)
        else:
            payload = pd.Series(value).to_numpy()
            index = []
    except Exception:
        # Хешируем по репрезентации — лучше «грубо, но стабильно», чем упасть.
        return hashlib.sha1(repr(value).encode("utf-8", errors="ignore")).hexdigest()[:16]
    h = hashlib.sha1()
    h.update(repr(index).encode("utf-8", errors="ignore"))
    try:
        h.update(payload.tobytes())
    except Exception:
        h.update(repr(payload).encode("utf-8", errors="ignore"))
    return h.hexdigest()[:16]


def _service_df_fingerprint(service_df: pd.DataFrame) -> str:
    """P0.1: fingerprint ``(population, capacity)`` для конкретного сервиса.

    Включает ровно то, что подаётся в LP (``population`` и ``capacity``), плюс индекс —
    чтобы запрос «для города N» и «для другого индекса» различались.
    """
    return _content_hash(service_df)


def _service_df(state: dict, data_dir, service_type: str) -> pd.DataFrame | str:
    blocks = ensure_blocks(state, data_dir)
    ensure_acc_mx(state, data_dir)
    cap_col = f"capacity_{service_type}"
    if cap_col not in blocks.columns:
        return _unknown_service_message(blocks, service_type)
    service_df = blocks[["population", cap_col]].copy()
    service_df = service_df.rename(columns={cap_col: "capacity"}).fillna(0)
    service_df["capacity"] = service_df["capacity"].astype(int)
    service_df["population"] = service_df["population"].astype(int)
    return service_df


def _resolve_single_service_type(service_type: str, blocks: pd.DataFrame, data_dir) -> str:
    available = _available_services(blocks)
    requested = str(service_type).strip()
    if requested in available:
        return requested
    try:
        from blocksnet_agent.tools.data import resolve_service_name

        resolved, _ranked = resolve_service_name(requested, data_dir, available)
        if resolved:
            return resolved
    except Exception:
        pass
    return requested


def _available_services(blocks: pd.DataFrame) -> list[str]:
    return sorted(c.replace("capacity_", "", 1) for c in blocks.columns if c.startswith("capacity_"))


def _unknown_service_message(blocks: pd.DataFrame, service_type: str) -> str:
    available = _available_services(blocks)
    lowered = str(service_type).strip().lower()
    presets = {"basic", "advanced", "comfort", "key"}
    land_uses = {item.name.lower() for item in LandUse}
    land_uses.update(str(item.value).lower() for item in LandUse)
    ranked = _rank_service_matches(str(service_type), available)
    close = [name for name, _score in ranked[:3]]
    examples = ", ".join(available[:20]) + (" ..." if len(available) > 20 else "")

    if lowered in presets:
        hint = (
            f"'{service_type}' похоже на пресет набора сервисов, а не на service_type. "
            "Для ключевых сервисов вызови list_key_services() и передай конкретное имя сервиса."
        )
    elif lowered in land_uses:
        hint = (
            f"'{service_type}' похоже на тип землепользования, а не на service_type. "
            "Для provision используй сервис из list_key_services() или list_service_types()."
        )
    else:
        hint = "Используй точное имя сервиса из list_service_types() или list_key_services()."

    suggestions = ""
    if ranked:
        suggestions = " Top candidates: " + ", ".join(f"{name} ({score:.2f})" for name, score in ranked[:5]) + "."
    elif close:
        suggestions = f" Ближайшие допустимые сервисы: {', '.join(close)}."
    return (
        f"Ошибка: тип сервиса '{service_type}' не найден. {hint}{suggestions}\n"
        f"Допустимые сервисы: {examples}"
    )


def _rank_service_matches(service_type: str, available: list[str]) -> list[tuple[str, float]]:
    query = str(service_type).strip().lower()
    if not query:
        return []
    # Единый data-driven резолвер: имена и синонимы берутся из каталога service_type.json
    # (name + name_ru + keywords) и data/service_aliases.json — без хардкода алиасов в коде.
    try:
        from blocksnet_agent.config import get_settings
        from blocksnet_agent.tools.data import rank_service_candidates

        ranked = rank_service_candidates(service_type, get_settings().data_dir, available)
        if ranked:
            return ranked
    except Exception:
        pass
    # Fallback (каталог недоступен): сопоставление только по каноническим именам.
    close = get_close_matches(query, available, n=5, cutoff=0.0)
    ranked = [
        (name, SequenceMatcher(None, query, name.lower()).ratio())
        for name in (close or available)
    ]
    return sorted(ranked, key=lambda item: item[1], reverse=True)


# T2: единая метка, отличающая общегородской агрегат от поквартального значения.
_AGG_NOTE = (
    "\n[это агрегат по городу, НЕ значение отдельного квартала; "
    "поквартально — get_block_info(block_id) или get_metric_for_block(result_key, block_id)]"
)


def _robust_summary(series: pd.Series) -> str:
    """D3: устойчивая сводка (медиана/перцентили/доля нулей), без опоры на неинформативное среднее."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return "нет числовых значений"
    zero_share = 100.0 * float((values <= 0).mean())
    return (
        f"кварталов: {len(values)}; медиана: {values.median():.3f}; "
        f"p25: {values.quantile(0.25):.3f}; p75: {values.quantile(0.75):.3f}; "
        f"макс: {values.max():.3f}; доля кварталов без обеспеченности: {zero_share:.0f}%"
    )


def _skew_note(series: pd.Series) -> str:
    """T2.3: предупреждает, когда среднее неинформативно из-за сильного перекоса/выбросов."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 3:
        return ""
    mean = float(values.mean())
    median = float(values.median())
    std = float(values.std())
    skewed = (std > 3 * abs(mean) and std > 0) or (median == 0 and mean != 0) or (abs(mean) > 3 * abs(median) and median != 0)
    if skewed:
        return (
            f"\n⚠ Распределение сильно скошено (mean={mean:.2f}, median={median:.2f}, std={std:.2f}): "
            "опирайся на медиану/перцентили и долю кварталов, а не на среднее — среднее здесь неинформативно."
        )
    return ""


def _provision_column(df: pd.DataFrame) -> str:
    for col in ("provision_strong", "provision", "provision_weak"):
        if col in df.columns:
            return col
    numeric_cols = df.select_dtypes(include="number").columns
    return numeric_cols[-1]


def _format_distribution_summary(df: pd.DataFrame, blocks: pd.DataFrame | None = None, top_n: int = 5) -> str:
    col = _provision_column(df)
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    if values.empty:
        return "Распределение: нет числовых поквартальных значений provision."
    lines = [
        "Распределение поквартальной обеспеченности:",
        _robust_summary(values),
    ]
    if blocks is not None:
        demand = block_demand_proxy(blocks.loc[blocks.index.intersection(values.index)]).reindex(values.index).fillna(0.0)
    else:
        demand = pd.Series(1.0, index=values.index, dtype="float64")
    positive = demand > 0
    deficit = pd.DataFrame({"provision": values.loc[positive], "demand_proxy": demand.loc[positive]})
    if not deficit.empty:
        deficit["deficit_score"] = (1.0 - deficit["provision"].clip(lower=0.0, upper=1.0)) * deficit["demand_proxy"].clip(lower=0.0)
        deficit = deficit.sort_values(["provision", "deficit_score", "demand_proxy"], ascending=[True, False, False]).head(top_n)
        lines.append("Top deficit rows (positive demand only):")
        for bid, row in deficit.iterrows():
            lines.append(
                f"- block_id {int(bid)}: provision={float(row['provision']):.4f}, "
                f"demand_proxy={float(row['demand_proxy']):.1f}, deficit_score={float(row['deficit_score']):.4f}"
            )
    else:
        lines.append("Top deficit rows: нет кварталов с положительным demand_proxy.")
    lines.append("Примечание: strong/weak — агрегаты по городу, не значения отдельного квартала.")
    return "\n".join(lines)


def _service_demand(service_type: str) -> int | None:
    try:
        if service_type in SERVICE_TYPES.index:
            demand = SERVICE_TYPES.loc[service_type, "demand"]
            return int(demand) if pd.notna(demand) else None
    except Exception:
        return None
    return None


def _service_accessibility(service_type: str, fallback: int) -> int:
    try:
        if service_type in SERVICE_TYPES.index:
            value = SERVICE_TYPES.loc[service_type, "accessibility"]
            return int(value) if pd.notna(value) else int(fallback)
    except Exception:
        return int(fallback)
    return int(fallback)


def _preset_services(preset: str, blocks: pd.DataFrame) -> list[str]:
    available = set(_available_services(blocks))
    lowered = str(preset).strip().lower()
    if lowered == "key":
        return sorted(name for name in available if name in set(SERVICE_TYPES.index))
    if lowered in _SERVICE_PRESETS:
        return [name for name in _SERVICE_PRESETS[lowered] if name in available]
    return []


def _provision_cache_params(state: dict, service_type: str, fingerprint: str, accessibility_minutes: int, max_depth: int) -> dict | None:
    """P0.1: параметры последнего расчёта provision для сервиса (None — если кэша нет).

    Ключ включает fingerprint ``(population, capacity)`` — чтобы cache-hit срабатывал
    при повторных вызовах с тем же сервисом и теми же кварталами (например, между
    ``compute_service_provision('school')`` и ``compute_scenario_provision`` для того
    же ``school``), и НЕ срабатывал при изменении capacity после сценарных добавлений.
    """
    return state.get(f"_params_competitive_provision_{service_type}_{fingerprint}")


def _provision_cache_hit(
    state: dict,
    service_type: str,
    fingerprint: str,
    accessibility_minutes: int,
    max_depth: int,
) -> dict | None:
    """P0.1: cache-hit по контенту входа (population+capacity+fingerprint), не по строковому ключу."""
    cached_params = _provision_cache_params(state, service_type, fingerprint, accessibility_minutes, max_depth)
    if cached_params is None:
        return None
    if (
        cached_params.get("accessibility_minutes") == accessibility_minutes
        and cached_params.get("max_depth") == max_depth
    ):
        return state.get(f"_summary_competitive_provision_{service_type}_{fingerprint}")
    return None


def _compute_single_service_provision(
    state: dict,
    data_dir,
    output_dir,
    service_type: str,
    accessibility_minutes: int,
    max_depth: int,
    save_artifacts: bool = True,
    *,
    service_df: pd.DataFrame | None = None,
) -> dict:
    """P0.1: provision для одного сервиса, кэш по контенту + LP-бюджет.

    Args:
        state: agent state; обновляется побочно (кэш результата и fingerprint).
        data_dir: путь к данным (для ``ensure_blocks/ensure_acc_mx``).
        output_dir: куда писать артефакты (CSV/PNG) при ``save_artifacts=True``.
        service_type: имя сервиса (lowercase каноническое).
        accessibility_minutes: порог доступности.
        max_depth: глубина конкуренции для LP.
        save_artifacts: сохранять ли CSV/карты (False для батча, чтобы не плодить файлы).
        service_df: опционально — заранее собранный ``service_df`` (для ``after_state``
            в ``compute_scenario_provision``, чтобы не пересобирать из БД).

    Поведение:
        1. ``service_df`` — это ``(population, capacity)`` для кварталов города. Его
           fingerprint входит в ключ кэша: если capacity изменился (например, сценарий
           добавил сервис), cache-hit НЕ сработает.
        2. LP-бюджет ``_LP_BUDGET`` защищает от «10 LP подряд» на одном запросе.
    """
    if service_df is None:
        service_df = _service_df(state, data_dir, service_type)
    if isinstance(service_df, str):
        raise ValueError(service_df)
    # type narrowing for mypy/pyright после return выше.
    assert isinstance(service_df, pd.DataFrame)
    fingerprint = _service_df_fingerprint(service_df)

    # P0.1: cache-hit по контенту входа + параметрам расчёта.
    cached = _provision_cache_hit(state, service_type, fingerprint, accessibility_minutes, max_depth)
    if cached is not None:
        return cached

    # P0.1: честный лимит LP. Если бюджет исчерпан — кэшируем пустой summary с пометкой
    # и возвращаем его; downstream увидит ``partial`` и не сможет делать вид, что всё ок.
    if _lp_budget_exceeded(state):
        summary = {
            "service_type": service_type,
            "accessibility_minutes": accessibility_minutes,
            "strong": float("nan"),
            "weak": float("nan"),
            "full": 0,
            "partial": 0,
            "missing": 0,
            "distribution": "",
            "lp_skipped": True,
            "lp_reason": f"LP budget {_LP_BUDGET} exceeded; дальнейшие вызовы не выполняются",
        }
        state[f"_summary_competitive_provision_{service_type}_{fingerprint}"] = summary
        state[f"_params_competitive_provision_{service_type}_{fingerprint}"] = {
            "accessibility_minutes": accessibility_minutes,
            "max_depth": max_depth,
        }
        return summary

    demand = _service_demand(service_type)
    result = competitive_provision(
        service_df,
        state["acc_mx"],
        accessibility_minutes,
        demand=demand,
        max_depth=max_depth,
    )
    _register_lp(state)  # P0.1: LP засчитан после реального вызова.

    blocks_prov = result[0] if isinstance(result, tuple) else result
    # D1: «текущий» результат провижина пишем в простой (без fingerprint) ключ —
    # именно его читают ``suggest_target_blocks``, ``get_metric_for_block`` и
    # сценарные инструменты. Контентный fingerprint-кэш защищает от двойного LP
    # при повторе с теми же кварталами, а «текущий» снимок — единый канонический
    # результат для агента.
    state[f"competitive_provision_{service_type}"] = blocks_prov
    # P0.1: контентный кэш — по fingerprint + параметрам расчёта.
    state[f"_params_competitive_provision_{service_type}_{fingerprint}"] = {
        "accessibility_minutes": accessibility_minutes,
        "max_depth": max_depth,
    }
    # T1.3: на диск (CSV/links/карты) пишем только вне батча — батч не должен плодить десятки файлов.
    if save_artifacts:
        if isinstance(result, tuple):
            for index, item in enumerate(result[1:], start=1):
                if isinstance(item, (pd.DataFrame, pd.Series)):
                    item.to_csv(output_dir / f"competitive_provision_{service_type}_links_{index}.csv")
        csv_path = output_dir / f"competitive_provision_{service_type}.csv"
        blocks_prov.to_csv(csv_path)
        record_file(csv_path, "csv", meta={"tool": "compute_service_provision", "service_type": service_type})
        save_metric_map(
            ensure_blocks(state, data_dir),
            blocks_prov,
            f"competitive_provision_{service_type}",
            output_dir,
            f"Обеспеченность {service_type}",
        )
    strong = provision_strong_total(blocks_prov)
    weak = provision_weak_total(blocks_prov)
    col = _provision_column(blocks_prov)
    values = pd.to_numeric(blocks_prov[col], errors="coerce").fillna(0)
    distribution = _format_distribution_summary(blocks_prov, ensure_blocks(state, data_dir))
    summary = {
        "service_type": service_type,
        "accessibility_minutes": accessibility_minutes,
        "strong": float(strong),
        "weak": float(weak),
        "full": int((values >= 1).sum()),
        "partial": int(((values > 0) & (values < 1)).sum()),
        "missing": int((values <= 0).sum()),
        "distribution": distribution,
    }
    # P0.1: контентный кэш summary — cache-hit в следующем вызове без LP.
    state[f"_summary_competitive_provision_{service_type}_{fingerprint}"] = summary
    return summary


def _compute_service_batch(
    state: dict,
    data_dir,
    output_dir,
    services: list[str],
    preset_name: str,
    accessibility_minutes: int,
    max_depth: int,
) -> str:
    rows: list[dict] = []
    errors: list[str] = []
    from blocksnet_agent.runtime import is_deadline_reached

    for service in services:
        # P0.2: проверка дедлайна между LP-расчётами батча — не запускаем новый
        # LP-прогон (до 4 мин), если дедлайн уже истёк.
        if is_deadline_reached():
            errors.append("прервано по дедлайну до обработки всех сервисов набора")
            break
        threshold = _service_accessibility(service, accessibility_minutes)
        try:
            rows.append(
                _compute_single_service_provision(
                    state, data_dir, output_dir, service, threshold, max_depth, save_artifacts=False
                )
            )
        except Exception as exc:
            errors.append(f"{service}: {exc}")

    if not rows:
        return (
            f"STOP_LP_BUDGET: ни один сервис из набора '{preset_name}' не посчитан "
            f"(вероятно, LP-бюджет исчерпан до старта батча). Завершай расчёты и "
            f"формируй финальный ответ на основе уже собранных данных."
        )

    summary_df = pd.DataFrame(rows)
    csv_path = output_dir / f"competitive_provision_batch_{preset_name}.csv"
    summary_df.to_csv(csv_path, index=False)
    record_file(csv_path, "csv", meta={"tool": "compute_service_provision", "service_type": preset_name, "batch": True})

    lines = [
        f"Батч-обеспеченность набора '{preset_name}' ({len(rows)} сервисов):",
        "| service | threshold_min | strong | weak | full_blocks | partial_blocks | missing_blocks | status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in sorted(rows, key=lambda item: item["strong"]):
        # P0.5 fix: при превышении LP-бюджета помечаем строку явно, чтобы модель
        # не путала nan с реальным отсутствием сервиса.
        if row.get("lp_skipped"):
            lines.append(
                f"| {row['service_type']} | - | SKIPPED | SKIPPED | - | - | - | LP-бюджет исчерпан |"
            )
            continue
        status = "слабая" if row["strong"] < 0.5 else "средняя" if row["strong"] < 0.75 else "сильная"
        lines.append(
            f"| {row['service_type']} | {row['accessibility_minutes']} | {row['strong']:.3f} | "
            f"{row['weak']:.3f} | {row['full']} | {row['partial']} | {row['missing']} | {status} |"
        )
    if errors:
        lines.append("Ошибки отдельных сервисов: " + "; ".join(errors))
    # P0.5 fix: если хотя бы один сервис батча был пропущен по LP-бюджету — даём
    # модели явный STOP-сигнал, иначе она не поймёт, почему часть значений nan/SKIPPED.
    if any(row.get("lp_skipped") for row in rows):
        lines.append(
            f"STOP_LP_BUDGET: часть сервисов батча пропущена из-за LP-бюджета "
            f"({sum(1 for row in rows if row.get('lp_skipped'))} из {len(rows)}). "
            f"Завершай расчёты и формируй финальный ответ на основе уже собранных данных."
        )
    lines.append(f"Сводный CSV: {csv_path}")
    return "\n".join(lines)


def make_provision_tools(ctx: dict) -> list:
    state = ctx["state"]
    data_dir = ctx["data_dir"]
    output_dir = ctx["output_dir"]

    @tool
    def compute_service_provision(service_type: str | list[str], accessibility_minutes: int | None = None, max_depth: int = 1) -> str:
        """Вычисляет конкурентную обеспеченность населения сервисом (или набором key/basic/advanced/comfort).

        Параметры: service_type — конкретный сервис из list_service_types() ИЛИ пресет
        'key'/'basic'/'advanced'/'comfort' (тогда считается батч по набору, сохраняется только сводка);
        accessibility_minutes — порог доступности (по умолчанию берётся из норматива SERVICE_TYPES,
        обычно 15 для школы и 60 для hospital); max_depth — глубина конкуренции.
        Выход: strong/weak provision (доля удовлетворённого спроса: strong — консервативная оценка,
        weak — расширенная) и число кварталов с полной/частичной/нулевой обеспеченностью.
        Подводные камни: не подменяй обеспеченность на compute_services_count (количество ≠ покрытие);
        service_type должен существовать среди capacity_*; если в list_key_services/list_service_types
        service помечен provision_available=False, demand-норматива нет и обеспеченность надо трактовать
        осторожно: лучше использовать capacity напрямую или близкий нормируемый сервис.

        Когда выбирать: чтобы оценить покрытие населения сервисом или найти кварталы с дефицитом.
        Не путать с: compute_services_count — количество объектов не равно обеспеченности спроса.
        """
        try:
            blocks = ensure_blocks(state, data_dir)
            requested = str(service_type).strip().lower() if isinstance(service_type, str) else ""
            batch_services = _preset_services(requested, blocks) if requested else []
            if batch_services:
                return _compute_service_batch(
                    state, data_dir, output_dir, batch_services, requested,
                    accessibility_minutes if accessibility_minutes is not None else 15, max_depth,
                )
            if isinstance(service_type, list):
                return _compute_service_batch(
                    state, data_dir, output_dir, [str(item) for item in service_type], "custom",
                    accessibility_minutes if accessibility_minutes is not None else 15, max_depth,
                )
            service_type = _resolve_single_service_type(str(service_type), blocks, data_dir)
            service_df = _service_df(state, data_dir, service_type)
            if isinstance(service_df, str):
                return service_df
            # P0.4: дефолт accessibility — из норматива SERVICE_TYPES, не всегда 15.
            effective_threshold = accessibility_minutes
            if effective_threshold is None:
                effective_threshold = _service_accessibility(service_type, 15)
            summary = _compute_single_service_provision(
                state, data_dir, output_dir, str(service_type), int(effective_threshold), int(max_depth)
            )
            # P0.5 fix: при превышении LP-бюджета возвращаем понятный STOP-маркер,
            # иначе модель видит "nan" без объяснения и продолжает вызывать другие
            # сервисы, сжигая оставшиеся итерации.
            if summary.get("lp_skipped"):
                return (
                    f"STOP_LP_BUDGET: {summary.get('lp_reason', 'LP budget exceeded')}. "
                    f"Дальнейшие compute_service_provision/compute_shared_provision "
                    f"вернут тот же результат. Завершай расчёты и формируй финальный "
                    f"ответ на основе уже собранных данных (get_analysis_results, "
                    f"get_block_info, get_metric_for_block)."
                )
            return (
                f"Обеспеченность сервисом '{summary['service_type']}' (порог {summary['accessibility_minutes']} мин):\n"
                f"Суммарная сильная обеспеченность: {summary['strong']:.3f}\n"
                f"Суммарная слабая обеспеченность: {summary['weak']:.3f}\n"
                f"Полная обеспеченность: {summary['full']} кварталов, "
                f"частичная: {summary['partial']}, отсутствует: {summary['missing']}."
                f"\n{summary.get('distribution', '')}"
                + _AGG_NOTE
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    @tool
    def compute_shared_provision(service_type: str | list[str], accessibility_minutes: int = 15) -> str:
        """Вычисляет совместную обеспеченность населения сервисом в заданном пороге доступности.

        Распределение обычно сильно скошено (у многих кварталов 0): опирайся на медиану, перцентили
        и долю кварталов без обеспеченности, а не на среднее. service_type — конкретный сервис или 'key'.
        """
        try:
            if service_type == "key":
                blocks = ensure_blocks(state, data_dir)
                service_type = [name for name in _available_services(blocks) if name in set(SERVICE_TYPES.index)][:6]
            if isinstance(service_type, list):
                return "\n\n".join(
                    compute_shared_provision.invoke({"service_type": item, "accessibility_minutes": accessibility_minutes})
                    for item in service_type
                )
            service_df = _service_df(state, data_dir, service_type)
            if isinstance(service_df, str):
                return service_df
            result = shared_provision(service_df, state["acc_mx"], accessibility_minutes)
            result_df = result[0] if isinstance(result, tuple) else result
            csv_path = output_dir / f"shared_provision_{service_type}.csv"
            result_df.to_csv(csv_path)
            record_file(csv_path, "csv", meta={"tool": "compute_shared_provision", "service_type": service_type})
            state[f"shared_provision_{service_type}"] = result_df
            save_metric_map(ensure_blocks(state, data_dir), result_df, f"shared_provision_{service_type}", output_dir, f"Совместная обеспеченность {service_type}")
            cols = [col for col in result_df.columns if "provision" in col.lower()]
            # D3: ведём сводку от медианы/перцентилей/доли нулей, а не от неинформативного среднего.
            if cols:
                summary = _robust_summary(result_df[cols[0]])
                note = _skew_note(result_df[cols[0]])
            else:
                summary = _robust_summary(result_df.select_dtypes(include="number").iloc[:, -1])
                note = ""
            return (
                f"Совместная обеспеченность '{service_type}' (порог {accessibility_minutes} мин):\n"
                f"{summary}{note}{_AGG_NOTE}"
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    return [compute_service_provision, compute_shared_provision]
