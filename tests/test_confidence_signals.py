"""P1.2: регресс-тесты на новую формулу confidence = Σwᵢ·sᵢ + basis."""
from __future__ import annotations

from blocksnet_agent.agent import _compute_confidence


def test_confidence_is_clamped_zero_with_no_evidence() -> None:
    confidence, basis = _compute_confidence(
        evidence_count=0,
        has_reflection=False,
        verified_hypotheses=0,
        has_unverified=False,
        grounding_gap=True,
        effect_gap=True,
        concreteness_gap=True,
        contradiction={"supported": 0, "refuted": 0, "inconclusive": 0},
    )
    assert 0.0 <= confidence <= 1.0
    # basis не пуст, есть все сигналы
    assert any("data_basis" in line for line in basis)
    assert any("penalty" in line for line in basis)


def test_confidence_is_high_with_full_evidence_no_penalties() -> None:
    confidence, _basis = _compute_confidence(
        evidence_count=3,
        has_reflection=True,
        verified_hypotheses=2,
        has_unverified=False,
        grounding_gap=False,
        effect_gap=False,
        concreteness_gap=False,
        contradiction={"supported": 2, "refuted": 0, "inconclusive": 0},
    )
    # data_basis=1.0, reflection=1.0, overlap=1.0, diversity=1.0, scarcity=1.0.
    # Σ = 0.30 + 0.10 + 0.20 + 0.10 + 0.10 = 0.80
    assert abs(confidence - 0.80) < 1e-6, f"expected 0.80, got {confidence}"


def test_confidence_penalises_grounding_gap() -> None:
    confidence_with, _ = _compute_confidence(
        evidence_count=2,
        has_reflection=True,
        verified_hypotheses=1,
        has_unverified=False,
        grounding_gap=False,
        effect_gap=False,
        concreteness_gap=False,
        contradiction={"supported": 1, "refuted": 0, "inconclusive": 0},
    )
    confidence_without, basis = _compute_confidence(
        evidence_count=2,
        has_reflection=True,
        verified_hypotheses=1,
        has_unverified=False,
        grounding_gap=True,
        effect_gap=False,
        concreteness_gap=False,
        contradiction={"supported": 1, "refuted": 0, "inconclusive": 0},
    )
    # grounding_gap влечёт -0.20 штрафа.
    assert abs((confidence_with - confidence_without) - 0.20) < 1e-6
    assert "penalty_grounding=-0.20" in basis


def test_confidence_basis_explains_each_signal() -> None:
    _, basis = _compute_confidence(
        evidence_count=2,
        has_reflection=True,
        verified_hypotheses=1,
        has_unverified=True,
        grounding_gap=False,
        effect_gap=False,
        concreteness_gap=False,
        contradiction={"supported": 1, "refuted": 0, "inconclusive": 0},
    )
    # basis должен покрывать 5 сигналов + 1 штраф за unverified.
    expected = {
        "data_basis",
        "reflection",
        "hypothesis_overlap",
        "tool_diversity",
        "scarcity",
        "penalty_unverified=-0.10",
    }
    basis_str = "\n".join(basis)
    for fragment in expected:
        assert fragment in basis_str, f"basis missing {fragment}: {basis_str}"


def test_confidence_inconclusive_only_dampens_but_does_not_kill() -> None:
    """P1.2: «inconclusive» — это штраф, не 0-confidence."""
    confidence, _ = _compute_confidence(
        evidence_count=2,
        has_reflection=True,
        verified_hypotheses=0,
        has_unverified=True,
        grounding_gap=False,
        effect_gap=False,
        concreteness_gap=False,
        contradiction={"supported": 0, "refuted": 0, "inconclusive": 3},
    )
    # scarcity = 1 - 1 = 0; data_basis=1.0; reflection=1.0; overlap=0.0; diversity=0.5.
    # penalty_unverified = -0.10. Σ = 0.30 + 0.10 + 0.00 + 0.05 + 0.00 - 0.10 = 0.35.
    assert abs(confidence - 0.35) < 1e-6
