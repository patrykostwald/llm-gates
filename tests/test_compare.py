from __future__ import annotations

from typing import Any

import pytest

from llm_gates import AgreementLevel, compare_outputs


def out(conclusion: Any = "yes", citations: str = "ab", confidence: Any = 0.8) -> dict[str, Any]:
    """Build an output; each character of ``citations`` is one citation id."""
    result: dict[str, Any] = {"conclusion": conclusion, "citations": list(citations)}
    if confidence is not None:
        result["confidence"] = confidence
    return result


def test_identical_outputs_agree() -> None:
    agreement = compare_outputs(out(), out())
    assert agreement.level is AgreementLevel.AGREE
    assert agreement.reasons == ()
    assert agreement.citation_jaccard == 1.0
    assert agreement.confidence_gap == 0.0
    assert agreement.shared_citations == ("a", "b")


def test_conclusions_are_normalised() -> None:
    assert compare_outputs(out("Yes "), out("  yes")).conclusions_match
    assert compare_outputs(out("not  liable"), out("NOT liable")).conclusions_match


def test_different_conclusions_disagree() -> None:
    agreement = compare_outputs(out("yes"), out("no"))
    assert agreement.level is AgreementLevel.DISAGREE
    assert not agreement.conclusions_match
    assert "conclusions differ" in agreement.reasons[0]


def test_missing_or_blank_conclusion_never_matches() -> None:
    assert compare_outputs({}, {}).level is AgreementLevel.DISAGREE
    assert compare_outputs(out(" "), out(" ")).level is AgreementLevel.DISAGREE


def test_non_string_conclusions_compare_by_equality() -> None:
    assert compare_outputs(out(True), out(True)).level is AgreementLevel.AGREE
    assert compare_outputs(out(True), out(False)).level is AgreementLevel.DISAGREE


def test_overlap_above_threshold_agrees() -> None:
    agreement = compare_outputs(out(citations="ab"), out(citations="abc"))  # Jaccard 2/3
    assert agreement.level is AgreementLevel.AGREE
    assert agreement.only_in_b == ("c",)
    assert agreement.only_in_a == ()


def test_low_overlap_is_partial() -> None:
    agreement = compare_outputs(out(citations="abc"), out(citations="dea"))  # Jaccard 1/5
    assert agreement.level is AgreementLevel.PARTIAL
    assert agreement.citation_jaccard == pytest.approx(0.2)
    assert "citation overlap" in agreement.reasons[0]


def test_overlap_exactly_at_threshold_is_not_penalised() -> None:
    agreement = compare_outputs(
        out(citations="ab"), out(citations="bc"), min_citation_jaccard=1 / 3
    )
    assert agreement.level is AgreementLevel.AGREE


def test_disjoint_citations_disagree_even_with_same_conclusion() -> None:
    agreement = compare_outputs(out(citations="a"), out(citations="b"))
    assert agreement.level is AgreementLevel.DISAGREE
    assert agreement.reasons == ("no shared citations",)


def test_one_side_without_citations_disagrees() -> None:
    assert compare_outputs(out(citations="a"), out(citations="")).level is AgreementLevel.DISAGREE


def test_both_sides_without_citations_agree() -> None:
    agreement = compare_outputs(out(citations=""), out(citations=""))
    assert agreement.level is AgreementLevel.AGREE
    assert agreement.citation_jaccard == 1.0


def test_confidence_gap_over_limit_is_partial() -> None:
    agreement = compare_outputs(out(confidence=0.9), out(confidence=0.4))
    assert agreement.level is AgreementLevel.PARTIAL
    assert agreement.confidence_gap == pytest.approx(0.5)


def test_confidence_gap_at_limit_is_fine() -> None:
    assert compare_outputs(out(confidence=0.5), out(confidence=0.8)).level is AgreementLevel.AGREE


def test_confidence_is_skipped_when_missing_or_not_numeric() -> None:
    assert compare_outputs(out(confidence=None), out()).confidence_gap is None
    assert compare_outputs(out(confidence="high"), out()).confidence_gap is None
    assert compare_outputs(out(confidence=True), out(confidence=0.1)).confidence_gap is None


def test_non_list_and_non_string_citations_are_ignored() -> None:
    assert compare_outputs({"citations": "a"}, out()).shared_citations == ()
    mixed = {"conclusion": "x", "citations": ["a", 1]}
    assert compare_outputs(mixed, out("x", "a")).shared_citations == ("a",)


def test_custom_field_names() -> None:
    a = {"verdict": "ok", "refs": ["r1"], "score": 0.5}
    agreement = compare_outputs(
        a, dict(a), conclusion_field="verdict", citations_field="refs", confidence_field="score"
    )
    assert agreement.level is AgreementLevel.AGREE


def test_multiple_reasons_accumulate() -> None:
    agreement = compare_outputs(out("yes", "abcd", 0.9), out("no", "dxyz", 0.1))
    assert agreement.level is AgreementLevel.DISAGREE
    assert len(agreement.reasons) == 3
