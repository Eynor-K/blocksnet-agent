"""Разбор параметров запуска из входящего A2A Message.

Три источника, строгий приоритет — **DataPart > metadata > дефолты**:

1. **DataPart** — канал, которым пользуется CodeSynapse. Их клиент извлекает
   значения из текста запроса по нашей JSON Schema (см.
   ``blocksnet_agent/a2a/extension.py``) и кладёт отдельной частью сообщения.
2. **metadata** — наш прежний канал (шаг 06 a2a-рефакторинга). CodeSynapse его
   **не заполняет**; остаётся ради обратной совместимости со smoke-скриптами и
   локальными клиентами, но проигрывает DataPart'у.
3. Отсутствие значения — не ошибка: ``resolve_context`` возьмёт дефолтный
   ``DATA_DIR``. Обязательных параметров у нас нет осознанно (см. A2).

Почему приоритет именно такой. У CodeSynapse это уже стоило боевого прогона:
запрос нёс ``scenario_id: 772`` текстом и устаревший DataPart ``987654321`` —
посчитан был ``987654321``, задача провалена (их ADR-0006). Их вывод —
«structure wins when both are present», и наша сторона обязана вести себя так
же предсказуемо, иначе один и тот же запрос даёт разные ответы у них и у нас.

Текст запроса при этом уходит агенту **неизменным**: клиент присылает полный
интент и рассчитывает, что агент сам игнорирует параметрические токены.
Вырезать их регулярками нельзя — потеряется смысл вопроса.

План: ``docs/dev/plans/codesynapse/01-a2a-contract.md`` (A3, A4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping

from blocksnet_agent.a2a.extension import PARAMS_SCHEMA, known_parameter_names

log = logging.getLogger("blocksnet_agent.a2a.params")

#: Откуда взято значение — для логов и диагностики.
SOURCE_DATA_PART = "data_part"
SOURCE_METADATA = "metadata"


class ParamValidationError(ValueError):
    """Структурно валидный DataPart с недопустимым значением параметра."""

    def __init__(self, message: str, *, param: str) -> None:
        super().__init__(message)
        self.param = param


@dataclass(frozen=True)
class ParsedParams:
    """Результат разбора: текст запроса и типизированные параметры."""

    question: str
    scenario_id: str | None = None
    project_id: str | None = None
    max_iterations: int | None = None
    #: ``{имя параметра: источник}`` — какой канал победил для каждого значения.
    sources: Dict[str, str] = field(default_factory=dict)

    def as_input_payload(self) -> Dict[str, Any]:
        """Полезная нагрузка для ``TaskManager.submit`` / skill runner."""
        return {
            "question": self.question,
            "max_iterations": self.max_iterations,
            "scenario_id": self.scenario_id,
            "project_id": self.project_id,
        }


def _coerce(name: str, value: Any) -> Any:
    """Привести значение к типу, объявленному в схеме расширения.

    Схема — источник истины по типам, поэтому спрашиваем её, а не хардкодим
    список. Значения приходят из LLM-извлечения на их стороне, поэтому число
    вполне может приехать строкой ``"12"`` — это не ошибка клиента.
    """
    spec = PARAMS_SCHEMA["properties"].get(name) or {}
    json_type = spec.get("type")

    if value is None:
        return None

    if json_type == "integer":
        if isinstance(value, bool):
            raise ParamValidationError(f"{name} must be an integer, got boolean", param=name)
        if isinstance(value, int):
            coerced = value
        elif isinstance(value, float) and value.is_integer():
            coerced = int(value)
        elif isinstance(value, str) and value.strip().lstrip("+-").isdigit():
            coerced = int(value.strip())
        else:
            raise ParamValidationError(
                f"{name} must be an integer, got {value!r}", param=name
            )
        minimum, maximum = spec.get("minimum"), spec.get("maximum")
        if minimum is not None and coerced < minimum:
            raise ParamValidationError(
                f"{name} must be >= {int(minimum)}, got {coerced}", param=name
            )
        if maximum is not None and coerced > maximum:
            raise ParamValidationError(
                f"{name} must be <= {int(maximum)}, got {coerced}", param=name
            )
        return coerced

    if json_type == "string":
        coerced = value if isinstance(value, str) else str(value)
        coerced = coerced.strip()
        if not coerced:
            return None
        return coerced

    return value


def extract_data_payload(parts: Iterable[Any]) -> Dict[str, Any]:
    """Слить ``data``-части сообщения в один словарь.

    В A2A 1.0 у Part нет дискриминатора ``kind``: тип определяется наличием
    ровно одного из ``text``/``raw``/``url``/``data``. У protobuf-Part
    ``data`` — это ``google.protobuf.Value``, и обращение к нему **всегда**
    возвращает объект, даже у текстовой части: пустое сообщение-по-умолчанию
    при этом истинно. Поэтому наличие проверяем через ``HasField('data')``, а
    не по истинности — иначе каждая текстовая часть выглядела бы как data.

    Несколько data-частей допустимы; более поздняя переопределяет раннюю.
    """
    payload: Dict[str, Any] = {}
    for part in parts or ():
        as_dict = _part_data_as_dict(part)
        if as_dict:
            payload.update(as_dict)
    return payload


def _part_data_as_dict(part: Any) -> Dict[str, Any] | None:
    """``data``-часть как обычный словарь, либо ``None``.

    Терпима и к protobuf-Part из SDK, и к простым объектам/словарям — так
    функцию можно прогнать без поднятия сервера.
    """
    has_field = getattr(part, "HasField", None)
    if callable(has_field):
        try:
            if not has_field("data"):
                return None
        except ValueError:  # поле не из этого oneof — не protobuf-Part
            return None
        struct_value = getattr(part.data, "struct_value", None)
        return dict(struct_value) if struct_value is not None else None

    data = part.get("data") if isinstance(part, Mapping) else getattr(part, "data", None)
    if data is None:
        return None
    try:
        return dict(data)
    except (TypeError, ValueError):
        log.warning("data part is not a mapping, ignored: %r", type(data))
        return None


def extract_text(parts: Iterable[Any]) -> str:
    """Склеить текстовые части. Текст уходит агенту без изменений."""
    return "".join(getattr(part, "text", "") or "" for part in parts or ())


def parse_message_params(
    parts: Iterable[Any],
    metadata: Mapping[str, Any] | None = None,
) -> ParsedParams:
    """Собрать ``ParsedParams`` из частей сообщения и metadata.

    Чистая функция: ``RequestContext`` сюда не заходит, поэтому её можно
    прогнать на голом Message. Вызов из ``execute()`` покрыт отдельным тестом —
    «написан, покрыт тестами и не вызван» здесь был бы ровно тем дефектом,
    который эта задача чинит.
    """
    parts = list(parts or ())
    question = extract_text(parts)
    data_payload = extract_data_payload(parts)
    meta = dict(metadata or {})

    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}

    for name in known_parameter_names():
        if name in data_payload and data_payload[name] is not None:
            raw, source = data_payload[name], SOURCE_DATA_PART
        elif name in meta and meta[name] not in (None, ""):
            raw, source = meta[name], SOURCE_METADATA
        else:
            continue

        coerced = _coerce(name, raw)
        if coerced is None:
            continue
        values[name] = coerced
        sources[name] = source

        if source == SOURCE_METADATA and name in data_payload:
            # data_payload[name] был None — DataPart есть, но значение пустое.
            log.debug("%s taken from metadata; data part carried no value", name)

    if data_payload and meta:
        overridden = [
            name for name in values
            if sources.get(name) == SOURCE_DATA_PART and name in meta
        ]
        if overridden:
            log.info(
                "DataPart overrides metadata for %s (structure wins on conflict)",
                ", ".join(sorted(overridden)),
            )

    return ParsedParams(
        question=question,
        scenario_id=values.get("scenario_id"),
        project_id=values.get("project_id"),
        max_iterations=values.get("max_iterations"),
        sources=sources,
    )


__all__ = [
    "ParamValidationError",
    "ParsedParams",
    "extract_data_payload",
    "extract_text",
    "parse_message_params",
    "SOURCE_DATA_PART",
    "SOURCE_METADATA",
]
