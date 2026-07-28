"""Profile Extension: структурированные параметры запуска для A2A-клиентов.

Зачем это существует
--------------------
CodeSynapse (Synapse) не читает ``message.metadata`` — канал, которым мы
пользовались раньше. Структурированные параметры он передаёт **DataPart'ом**,
а какие именно параметры существуют и какого они типа, узнаёт из
``capabilities.extensions[].params`` нашей Agent Card: это JSON Schema, по
которой он делает один schema-constrained LLM-вызов и извлекает значения из
текста запроса (их ADR-0006).

Ключевое следствие: **схема здесь — единственный источник имён и типов**.
Добавить параметр = поправить эту схему; на их стороне не меняется ничего.
Дублировать эти имена где-то ещё нельзя — разойдётся.

Гейт извлечения — ``required: true`` у самого расширения
(``required_extensions_with_schema`` в их ``a2a_params.py``). Без него их
клиент не делает ни LLM-вызова, ни заголовка ``A2A-Extensions``, и параметры
до нас не доезжают вообще.

Что такое ``scenario_id`` без UrbanDB
-------------------------------------
UrbanDB сознательно **не подключён**: blocksnet требует специфично
подготовленных данных, которых UrbanDB не отдаёт. Поэтому ``scenario_id`` — это
имя заранее подготовленного датасета, смонтированного на инстанс
(``DATA_DIR/<scenario_id>``), а не идентификатор сценария в MAS. Несуществующее
имя даёт штатный ``SCENARIO_NOT_MATERIALIZED`` со списком доступных датасетов,
чтобы вызывающий агент мог исправиться сам.

Отсюда формулировка в описании параметра: клиентская LLM не должна выводить
значение из топонимов в тексте вопроса — только из явно названного датасета.

Почему ``required`` внутри схемы пуст
------------------------------------
Их ``_coerce_and_validate`` роняет запрос **до обращения к нам**, если
required-параметр не извлёкся. Мы этим намеренно не пользуемся: анализ без
``scenario_id`` возможен и осмыслен — ``resolve_context`` берёт дефолтный
``DATA_DIR`` (одногородская установка, локальный режим, smoke-прогоны).
Требовать ``scenario_id`` значило бы ломать все запросы, не называющие
сценарий, ради защиты от случая, который закрыт иначе: параметры теперь
доезжают (A3), а заведомо неверные значения падают громко (A7).

Отсутствующие опциональные параметры их код **отбрасывает, а не выдумывает**
("Absent optional properties are dropped, never fabricated").

План: ``docs/dev/plans/codesynapse/01-a2a-contract.md`` (A2).
Контракт: ``docs/dev/codesynapse/docs/contracts/a2a/synapse-a2a-1.0-contract.md``
(``$defs.synapseParameterExtension``).
"""

from __future__ import annotations

from typing import Any, Dict

# Стабильный версионированный URI. Меняется только при несовместимом изменении
# схемы: клиенты активируют расширение по нему через заголовок A2A-Extensions.
EXTENSION_URI = "https://blocksnet.itmo.ru/extensions/urban-task-input/v1"

EXTENSION_DESCRIPTION = (
    "Structured run parameters for BlocksNet urban analysis: which scenario and "
    "project the question is about, and an optional agent iteration budget."
)

# Регулярка совпадает с _SCENARIO_ID_PATTERN в blocksnet_agent/context.py.
# Расхождение здесь означало бы, что клиент пришлёт значение, которое наш же
# resolve_context отвергнет как VALIDATION_ERROR.
_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"

#: JSON Schema параметров. Публикуется в Agent Card как ``params`` расширения
#: и используется их стороной как ``input_schema`` forced-tool вызова.
PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "scenario_id": {
            "type": "string",
            "pattern": _ID_PATTERN,
            "description": (
                "Name of a pre-provisioned urban dataset to analyse (for example a "
                "city or district dataset mounted on this instance). Use it ONLY "
                "when the request names such a dataset explicitly; do not invent or "
                "derive a value from place names mentioned in passing. Omit it to "
                "analyse the instance's default dataset."
            ),
        },
        "project_id": {
            "type": "string",
            "pattern": _ID_PATTERN,
            "description": (
                "Identifier of the MAS project the run belongs to. "
                "Omit when the request does not name a project."
            ),
        },
        "max_iterations": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "description": (
                "Optional cap on agent reasoning iterations. Omit unless the request "
                "explicitly limits the analysis budget."
            ),
        },
    },
    # Пусто осознанно — см. модульный докстринг.
    "required": [],
    "additionalProperties": False,
}


def build_parameter_extension() -> Dict[str, Any]:
    """Объект расширения для ``capabilities.extensions`` Agent Card."""
    return {
        "uri": EXTENSION_URI,
        "description": EXTENSION_DESCRIPTION,
        "required": True,
        "params": PARAMS_SCHEMA,
    }


def known_parameter_names() -> tuple[str, ...]:
    """Имена параметров — берутся из схемы, а не дублируются списком."""
    return tuple(PARAMS_SCHEMA["properties"])


__all__ = [
    "EXTENSION_URI",
    "EXTENSION_DESCRIPTION",
    "PARAMS_SCHEMA",
    "build_parameter_extension",
    "known_parameter_names",
]
