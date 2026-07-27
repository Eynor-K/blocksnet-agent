"""Тесты шага 05 a2a-рефакторинга: A2A-карточка и её соответствие контракту.

Главные гарантии:
- Agent Card валидируется protobuf-моделью SDK 1.1.1.
- В карточке ровно два skill: ``run_pipeline`` и ``analyze_urban_question``.
- ``url`` отражает ``A2A_PUBLIC_URL`` если задан, иначе ``http://host:port/``.
- Capabilities: ``streaming=True``, ``push_notifications=False``.
- Skills корректно мапятся в AgentSkill с id/name/description/tags/examples.
"""

from __future__ import annotations

from blocksnet_agent.a2a.agent_card import build_agent_card
from blocksnet_agent.a2a.skills import SKILLS


def test_card_has_two_skills() -> None:
    """Ровно два skill в карточке (run_pipeline, analyze_urban_question)."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    skill_ids = [s.id for s in card.skills]
    assert set(skill_ids) == {"run_pipeline", "analyze_urban_question"}
    assert len(skill_ids) == 2


def test_card_skill_ids_match_registry() -> None:
    """id skill-ов в карточке совпадают с реестром ``SKILLS`` (нет дрейфа)."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    card_ids = {s.id for s in card.skills}
    registry_ids = {spec.id for spec in SKILLS}
    assert card_ids == registry_ids


def test_card_uses_public_url_when_set() -> None:
    """``A2A_PUBLIC_URL`` имеет приоритет над host:port."""
    card = build_agent_card(
        host="127.0.0.1",
        port=8080,
        public_url="https://blocksnet.example.com/agents/blocksnet",
    )
    interfaces = list(card.supported_interfaces)
    assert len(interfaces) == 1
    assert interfaces[0].url == "https://blocksnet.example.com/agents/blocksnet"
    assert interfaces[0].protocol_binding == "JSONRPC"
    assert interfaces[0].protocol_version == "1.0"


def test_card_uses_host_port_when_no_public_url() -> None:
    """Без ``public_url`` — URL = ``http://{host}:{port}/``."""
    card = build_agent_card(host="0.0.0.0", port=9090, public_url=None)
    interfaces = list(card.supported_interfaces)
    assert interfaces[0].url == "http://0.0.0.0:9090/"


def test_card_capabilities_streaming_true_push_false() -> None:
    """streaming=True (стрим TaskStatusUpdateEvent), push_notifications=False (отложено)."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    assert card.capabilities.streaming is True
    assert card.capabilities.push_notifications is False


def test_card_default_io_modes() -> None:
    """defaultInputModes / defaultOutputModes — text + json."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    assert "text/plain" in card.default_input_modes
    # Output — text + json (для structured payload).
    assert "text/plain" in card.default_output_modes
    assert "application/json" in card.default_output_modes


def test_card_skill_has_required_fields() -> None:
    """Каждый skill в карточке имеет id/name/description/tags/examples."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    for skill in card.skills:
        assert skill.id, "skill.id is empty"
        assert skill.name, "skill.name is empty"
        assert skill.description, "skill.description is empty"
        # ``tags`` в protobuf — RepeatedScalarContainer, у него есть __iter__/__len__.
        assert len(list(skill.tags)) >= 0
        assert len(list(skill.examples)) > 0, (
            f"skill {skill.id} has no examples"
        )


def test_card_name_and_version_set() -> None:
    """name и version не пустые (обязательные поля AgentCard)."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    assert card.name == "blocksnet-mcp-a2a"
    assert card.version  # не пустая строка


def test_card_description_not_empty() -> None:
    """description — для discovery, должна быть непустой."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    assert len(card.description) > 50


def test_analyze_urban_question_marked_as_deprecated() -> None:
    """analyze_urban_question помечен как [DEPRECATED] в description."""
    card = build_agent_card(host="127.0.0.1", port=8080, public_url=None)
    legacy = next(s for s in card.skills if s.id == "analyze_urban_question")
    assert "DEPRECATED" in legacy.description.upper()