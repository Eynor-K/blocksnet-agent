from typing import Any, TypedDict


class AgentResult(TypedDict, total=False):
    input: str
    output: str
    log: list[Any]
    # Метакогнитивные поля структурированного вывода:
    confidence: float
    limitations: list[str]
    sections: dict[str, str]
    run_dir: str
    # P1.1: payload терминального ``submit_answer``. Если задан — ``to_json`` отдаёт
    # его в ``structuredContent`` MCP-вызова; иначе fallback с regex-парсингом
    # и ``salvaged: True``.
    submitted_answer: dict[str, Any]
    # P1.6: результат ``overlay_candidates`` — структурный список кандидатов и
    # мета (hard_passed/diagnostic_layers). ``to_json`` использует его в качестве
    # fallback-source для ``recommendation_blocks`` (приоритетнее regex-парсинга).
    overlay_recommendations: list[dict[str, Any]]
    overlay_meta: dict[str, Any]
    # P1.2: basis confidence — список сигналов, которые на него повлияли
    # (например, ``data_basis=1.0*0.30=+0.30``). Полезно для audit/MAS.
    confidence_basis: list[str]
    # P0.5: индекс валидных block_id для фильтрации recommendation_blocks в salvage-пути.
    # Если задан, ``to_json`` выбрасывает block_id, которых нет в этом наборе
    # (защита от регэксп-экстракции мусора из чужого текста).
    valid_block_ids: list[int]


def __getattr__(name: str) -> Any:
    if name == "BlocksNetAgent":
        from blocksnet_agent.agent import BlocksNetAgent

        return BlocksNetAgent
    raise AttributeError(name)


__all__ = ["AgentResult", "BlocksNetAgent"]
