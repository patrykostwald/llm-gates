from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from llm_gates import (
    Field,
    GateContext,
    NearMiss,
    NearMissKind,
    NearMissRule,
    Norm,
    NormRegistry,
    PublicationGate,
    Schema,
    Verdict,
    find_near_misses,
)

TODAY = date(2026, 6, 15)


def registry(*ids: str) -> NormRegistry:
    return NormRegistry(Norm(norm_id, "Title", date(2020, 1, 1)) for norm_id in ids)


def dense(count: int = 40) -> NormRegistry:
    """Consecutive numbering: ACT-001, ACT-002, ..."""
    return registry(*(f"ACT-{n:03d}" for n in range(1, count + 1)))


def misses(cited: list[Any], reg: NormRegistry, **options: Any) -> list[tuple[str, str, str]]:
    found = find_near_misses({"citations": cited}, reg, TODAY, **options)
    return [(m.citation, m.neighbour, m.kind.value) for m in found]


# --- swaps ---------------------------------------------------------------------------------


def test_swap_twin_is_reported_even_in_a_dense_registry() -> None:
    assert misses(["ACT-012"], dense()) == [("ACT-012", "ACT-021", "swap")]
    assert misses(["ACT-001"], dense()) == [("ACT-001", "ACT-010", "swap")]


def test_both_directions_are_reported_when_only_one_id_is_cited() -> None:
    assert misses(["ACT-021"], dense()) == [("ACT-021", "ACT-012", "swap")]


def test_no_report_when_the_output_cites_both_ids() -> None:
    assert misses(["ACT-012", "ACT-021"], dense()) == []


def test_swap_with_a_norm_that_is_not_in_force_is_ignored() -> None:
    reg = NormRegistry(
        [
            Norm("ACT-003", "Current", date(2020, 1, 1)),
            Norm("ACT-030", "Repealed", date(2000, 1, 1), date(2010, 1, 1)),
            Norm("ACT-300", "Not yet", date(2030, 1, 1)),
        ]
    )
    assert misses(["ACT-003"], reg) == []


def test_swap_needs_two_different_adjacent_characters() -> None:
    # same letters in another order but not an adjacent exchange
    assert misses(["ACT-123"], registry("ACT-123", "ACT-321")) == []
    # a swap of equal characters is the same id, not a neighbour
    assert misses(["ACT-110"], registry("ACT-110")) == []


# --- edits and density ---------------------------------------------------------------------


def test_dense_numbering_does_not_make_every_id_suspicious() -> None:
    # ACT-005 has eight neighbours one digit away; that is what numbering looks like
    reg = registry(*(f"ACT-00{n}" for n in range(1, 10)))
    assert misses(["ACT-005"], reg) == []


def test_sparse_registry_reports_a_single_character_slip() -> None:
    reg = registry("LAW-4410", "LAW-4420", "DIR-2019-07")
    assert misses(["LAW-4410"], reg) == [("LAW-4410", "LAW-4420", "edit")]


@pytest.mark.parametrize(
    ("cited", "other"),
    [
        ("LAW-4410", "LAW-410"),  # one character missing
        ("LAW-410", "LAW-4410"),  # one character added
        ("LAW-4410", "LAW-4411"),  # one character replaced
    ],
)
def test_insertions_deletions_and_substitutions_are_edits(cited: str, other: str) -> None:
    assert misses([cited], registry(cited, other)) == [(cited, other, "edit")]


def test_edit_threshold_is_configurable() -> None:
    reg = registry("LAW-4410", "LAW-4411", "LAW-4412", "LAW-4413")
    assert misses(["LAW-4410"], reg) == []  # three neighbours: looks like numbering
    assert len(misses(["LAW-4410"], reg, max_edit_neighbours=3)) == 3
    assert misses(["LAW-4410"], registry("LAW-4410", "LAW-4411"), max_edit_neighbours=0) == []


def test_ids_of_different_length_need_exactly_one_missing_character() -> None:
    assert misses(["LAW-4410"], registry("LAW-4410", "LAW-4X1")) == []  # one shorter, not an edit
    assert misses(["LAW-4410"], registry("LAW-4410", "LAW-4")) == []  # four shorter


def test_cited_neighbours_still_count_towards_density_but_are_not_reported() -> None:
    reg = registry("LAW-4410", "LAW-4411", "LAW-4412")
    assert misses(["LAW-4410", "LAW-4411"], reg) == [
        ("LAW-4410", "LAW-4412", "edit"),
        ("LAW-4411", "LAW-4412", "edit"),
    ]
    assert misses(["LAW-4410", "LAW-4411", "LAW-4412"], reg) == []


# --- what is left to the citation check -------------------------------------------------------


def test_short_ids_are_skipped() -> None:
    assert misses(["A-1"], registry("A-1", "A-2")) == []


def test_unknown_malformed_and_out_of_force_citations_are_not_near_misses() -> None:
    reg = NormRegistry(
        [
            Norm("ACT-012", "Repealed", date(2000, 1, 1), date(2010, 1, 1)),
            Norm("ACT-021", "Current", date(2000, 1, 1)),
        ]
    )
    assert misses(["ACT-012"], reg) == []  # repealed: a citation problem, not a near miss
    assert misses(["ACT-999", "two words", 7, None, ["ACT-021"]], reg) == []


def test_duplicates_are_reported_once() -> None:
    assert misses(["ACT-012", "ACT-012"], dense()) == [("ACT-012", "ACT-021", "swap")]


def test_missing_or_misshapen_field_is_clean() -> None:
    assert find_near_misses({}, dense(), TODAY) == []
    assert find_near_misses({"citations": "ACT-012"}, dense(), TODAY) == []
    found = find_near_misses({"refs": ["ACT-012"]}, dense(), TODAY, field="refs")
    assert [m.neighbour for m in found] == ["ACT-021"]


def test_results_follow_citation_order_then_registry_order() -> None:
    found = misses(["ACT-012", "ACT-001"], dense())
    assert found == [("ACT-012", "ACT-021", "swap"), ("ACT-001", "ACT-010", "swap")]


def test_near_miss_text_and_registry_iteration() -> None:
    swap = NearMiss("ACT-012", "ACT-021", NearMissKind.SWAP)
    edit = NearMiss("LAW-4410", "LAW-4420", NearMissKind.EDIT)
    assert str(swap) == (
        "ACT-012 is a swap of two adjacent characters away from ACT-021, which is also in force"
    )
    assert str(edit) == "LAW-4410 is one edit away from LAW-4420, which is also in force"
    assert [norm.id for norm in registry("A-100", "B-200")] == ["A-100", "B-200"]


# --- the rule and the default gate ------------------------------------------------------------

SCHEMA = Schema(
    {
        "conclusion": Field(str),
        "confidence": Field(float, minimum=0, maximum=1),
        "citations": Field(list, items=Field(str), min_items=1),
    }
)


def output(*citations: str) -> dict[str, Any]:
    return {"conclusion": "liable", "confidence": 0.8, "citations": list(citations)}


def test_rule_sends_a_near_miss_to_review_with_a_readable_reason() -> None:
    context = GateContext(output("ACT-012"), TODAY)
    (finding,) = NearMissRule(dense()).check(context)
    assert finding.verdict is Verdict.REVIEW
    assert finding.rule == "near-miss"
    assert str(finding) == (
        "[review] near-miss: ACT-012 is a swap of two adjacent characters away from ACT-021, "
        "which is also in force"
    )


def test_rule_options_are_passed_through() -> None:
    context = GateContext({"refs": ["LAW-4410"]}, TODAY)
    reg = registry("LAW-4410", "LAW-4411")
    assert NearMissRule(reg).check(context) == []  # wrong field name, nothing cited
    assert len(NearMissRule(reg, field="refs").check(context)) == 1
    assert NearMissRule(reg, field="refs", max_edit_neighbours=0).check(context) == []


def test_default_gate_includes_the_rule_after_the_citation_check() -> None:
    names = [rule.name for rule in PublicationGate.default(SCHEMA, dense()).rules]
    assert names == ["schema", "citations", "near-miss", "pii", "agreement"]


def test_default_gate_can_leave_the_rule_out() -> None:
    gate = PublicationGate.default(SCHEMA, dense(), near_miss=False)
    assert "near-miss" not in [rule.name for rule in gate.rules]
    decision = gate.evaluate(output("ACT-012"), as_of=TODAY, second_opinion=output("ACT-012"))
    assert decision.verdict is Verdict.PUBLISH


def test_default_gate_reviews_a_near_miss_and_publishes_the_clean_neighbourhood() -> None:
    gate = PublicationGate.default(SCHEMA, dense())
    slip = output("ACT-012")
    held = gate.evaluate(slip, as_of=TODAY, second_opinion=slip)
    assert held.verdict is Verdict.REVIEW
    assert [b.rule for b in held.blockers] == ["near-miss"]
    both = output("ACT-012", "ACT-021")
    assert gate.evaluate(both, as_of=TODAY, second_opinion=both).verdict is Verdict.PUBLISH
    numbered = output("ACT-005")
    assert gate.evaluate(numbered, as_of=TODAY, second_opinion=numbered).verdict is Verdict.PUBLISH


def test_a_citation_problem_still_outranks_a_near_miss() -> None:
    gate = PublicationGate.default(SCHEMA, dense())
    mixed = output("ACT-012", "ACT-999")
    decision = gate.evaluate(mixed, as_of=TODAY, second_opinion=mixed)
    assert decision.verdict is Verdict.REJECT
    assert [b.rule for b in decision.blockers] == ["citations", "near-miss"]
