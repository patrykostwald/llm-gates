from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from llm_gates import (
    AgreementRule,
    CitationRule,
    Decision,
    Field,
    Finding,
    GateContext,
    Norm,
    NormRegistry,
    PiiRule,
    PublicationGate,
    Schema,
    SchemaRule,
    Verdict,
)

TODAY = date(2025, 6, 1)
SCHEMA = Schema(
    {
        "conclusion": Field(str),
        "confidence": Field(float, minimum=0, maximum=1),
        "citations": Field(list, items=Field(str), min_items=1),
    }
)
REGISTRY = NormRegistry(
    [
        Norm("art-1", "One", date(2020, 1, 1)),
        Norm("art-2", "Two", date(2020, 1, 1)),
        Norm("old", "Repealed", date(2000, 1, 1), date(2010, 1, 1)),
    ]
)
GOOD: dict[str, Any] = {"conclusion": "liable", "confidence": 0.8, "citations": ["art-1", "art-2"]}


def gate() -> PublicationGate:
    return PublicationGate.default(SCHEMA, REGISTRY)


def evaluate(output: object, second: dict[str, Any] | None = GOOD) -> Decision:
    return gate().evaluate(output, as_of=TODAY, second_opinion=second)


def test_clean_output_is_published() -> None:
    decision = evaluate(GOOD)
    assert decision.verdict is Verdict.PUBLISH
    assert decision.publishable
    assert decision.blockers == ()
    assert decision.reasons == ()


def test_schema_error_rejects() -> None:
    decision = evaluate({**GOOD, "confidence": "high"})
    assert decision.verdict is Verdict.REJECT
    assert not decision.publishable
    assert decision.reasons == ("[reject] schema: $.confidence: expected number, got string",)


def test_unknown_norm_rejects() -> None:
    decision = evaluate({**GOOD, "citations": ["art-1", "art-99"]})
    assert decision.verdict is Verdict.REJECT
    assert decision.blockers[0].rule == "citations"


def test_norm_not_in_force_rejects() -> None:
    assert evaluate({**GOOD, "citations": ["old"]}).verdict is Verdict.REJECT


def test_pii_sends_to_review_without_leaking_the_value() -> None:
    leaky = {**GOOD, "conclusion": "write to jan@example.com"}
    decision = evaluate(leaky, leaky)
    assert decision.verdict is Verdict.REVIEW
    assert decision.reasons == ("[review] pii: possible email at $.conclusion",)
    assert "jan@example.com" not in str(decision)


def test_disagreeing_second_model_sends_to_review() -> None:
    decision = evaluate(GOOD, {**GOOD, "conclusion": "not liable"})
    assert decision.verdict is Verdict.REVIEW
    assert decision.blockers[0].rule == "agreement"
    assert "models disagree" in decision.reasons[0]


def test_partial_agreement_also_sends_to_review() -> None:
    decision = evaluate(GOOD, {**GOOD, "confidence": 0.1})
    assert decision.verdict is Verdict.REVIEW
    assert "models partial" in decision.reasons[0]


def test_missing_second_opinion_sends_to_review_by_default() -> None:
    decision = evaluate(GOOD, None)
    assert decision.verdict is Verdict.REVIEW
    assert decision.reasons == ("[review] agreement: no second opinion provided",)


def test_second_opinion_can_be_optional() -> None:
    optional = PublicationGate([AgreementRule(required=False)])
    assert optional.evaluate(GOOD, as_of=TODAY).verdict is Verdict.PUBLISH


def test_reject_outranks_review_and_all_blockers_are_listed() -> None:
    bad = {**GOOD, "conclusion": "a@b.pl", "citations": ["art-99"]}
    decision = evaluate(bad, None)
    assert decision.verdict is Verdict.REJECT
    assert [b.rule for b in decision.blockers] == ["citations", "pii", "agreement"]


def test_non_object_output_is_rejected_outright() -> None:
    decision = evaluate(["not", "an", "object"])
    assert decision.verdict is Verdict.REJECT
    assert decision.reasons == ("[reject] gate: output is not a JSON object",)


class ForbiddenWords:
    """A custom rule: review anything promising a guarantee."""

    name = "forbidden-words"

    def check(self, context: GateContext) -> Sequence[Finding]:
        if "guarantee" in str(context.output.get("conclusion", "")):
            return [Finding(self.name, Verdict.REVIEW, "promises a guarantee")]
        return []


def test_custom_rule_can_be_added() -> None:
    custom = gate()
    custom.add_rule(ForbiddenWords())
    promise = {**GOOD, "conclusion": "we guarantee it"}
    decision = custom.evaluate(promise, as_of=TODAY, second_opinion=promise)
    assert decision.verdict is Verdict.REVIEW
    assert decision.blockers[0].rule == "forbidden-words"


def test_findings_with_publish_verdict_do_not_block() -> None:
    class Noisy:
        name = "noisy"

        def check(self, context: GateContext) -> Sequence[Finding]:
            return [Finding(self.name, Verdict.PUBLISH, "fyi")]

    decision = PublicationGate([Noisy()]).evaluate(GOOD, as_of=TODAY)
    assert decision.verdict is Verdict.PUBLISH
    assert decision.blockers == ()


def test_gate_without_rules_publishes_any_object() -> None:
    assert PublicationGate([]).evaluate({}, as_of=TODAY).verdict is Verdict.PUBLISH


def test_individual_rules_are_usable_alone() -> None:
    context = GateContext(GOOD, TODAY)
    assert SchemaRule(SCHEMA).check(context) == []
    assert CitationRule(REGISTRY).check(context) == []
    assert PiiRule().check(context) == []
    assert CitationRule(REGISTRY, field="refs", name="refs").check(context) == []


def test_verdict_severity_order_and_finding_string() -> None:
    assert Verdict.PUBLISH.severity < Verdict.REVIEW.severity < Verdict.REJECT.severity
    assert str(Finding("r", Verdict.REVIEW, "why")) == "[review] r: why"


def test_decision_is_deterministic() -> None:
    assert evaluate(GOOD) == evaluate(GOOD)
