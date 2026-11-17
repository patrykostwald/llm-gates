"""Compose rules into a publication gate.

A :class:`PublicationGate` runs a list of :class:`Rule` objects over a model
output. Each rule returns zero or more :class:`Finding` objects; the gate's
:class:`Decision` is the most severe verdict among them (``reject`` beats
``review`` beats ``publish``). Nothing is decided by a model: the same input
always yields the same decision.

Exceptions raised by a rule propagate. A broken rule must never turn into a
silent ``publish``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Protocol

from llm_gates.citations import (
    DEFAULT_MAX_EDIT_NEIGHBOURS,
    NormRegistry,
    find_near_misses,
    verify_citations,
)
from llm_gates.compare import AgreementLevel, compare_outputs
from llm_gates.pii import find_pii
from llm_gates.schema import Schema


class Verdict(str, Enum):
    """What should happen to an output."""

    PUBLISH = "publish"
    REVIEW = "review"
    REJECT = "reject"

    @property
    def severity(self) -> int:
        """Ordering used to pick the worst verdict: publish < review < reject."""
        return _SEVERITY[self]


_SEVERITY = {Verdict.PUBLISH: 0, Verdict.REVIEW: 1, Verdict.REJECT: 2}


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason a rule objects to an output."""

    rule: str
    verdict: Verdict
    reason: str

    def __str__(self) -> str:
        return f"[{self.verdict.value}] {self.rule}: {self.reason}"


@dataclass(frozen=True, slots=True)
class GateContext:
    """Everything a rule may look at."""

    output: Mapping[str, Any]
    as_of: date
    second_opinion: Mapping[str, Any] | None = None


class Rule(Protocol):
    """A deterministic check. Implement ``name`` and ``check`` to add your own."""

    @property
    def name(self) -> str:
        """Short identifier shown in findings."""
        ...

    def check(self, context: GateContext) -> Sequence[Finding]:
        """Return findings for objections; an empty sequence means "no objection"."""
        ...


@dataclass(frozen=True, slots=True)
class Decision:
    """The gate's answer, with the findings that justify it."""

    verdict: Verdict
    blockers: tuple[Finding, ...] = field(default=())

    @property
    def reasons(self) -> tuple[str, ...]:
        """Human-readable explanation of each blocker."""
        return tuple(str(blocker) for blocker in self.blockers)

    @property
    def publishable(self) -> bool:
        """True only for a clean ``publish``."""
        return self.verdict is Verdict.PUBLISH


class PublicationGate:
    """Runs rules in order and combines their findings into a :class:`Decision`."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self.rules: list[Rule] = list(rules)

    def add_rule(self, rule: Rule) -> None:
        """Append a rule."""
        self.rules.append(rule)

    @classmethod
    def default(
        cls, schema: Schema, registry: NormRegistry, *, near_miss: bool = True
    ) -> PublicationGate:
        """The default policy: schema and citations reject; near-miss citations,
        PII and model disagreement send the output to a human.

        Pass ``near_miss=False`` to leave out :class:`NearMissRule`, for example
        when your registry numbers its norms so densely that the rule is noisy.
        """
        rules: list[Rule] = [SchemaRule(schema), CitationRule(registry)]
        if near_miss:
            rules.append(NearMissRule(registry))
        return cls([*rules, PiiRule(), AgreementRule()])

    def evaluate(
        self,
        output: object,
        *,
        as_of: date,
        second_opinion: Mapping[str, Any] | None = None,
    ) -> Decision:
        """Run every rule over ``output`` and return the decision.

        Args:
            output: the parsed model output; anything but a JSON object is rejected.
            as_of: the date on which cited norms must be in force.
            second_opinion: an independent output for :class:`AgreementRule`.
        """
        if not isinstance(output, Mapping):
            finding = Finding("gate", Verdict.REJECT, "output is not a JSON object")
            return Decision(Verdict.REJECT, (finding,))
        context = GateContext(output, as_of, second_opinion)
        blockers = tuple(
            finding
            for rule in self.rules
            for finding in rule.check(context)
            if finding.verdict is not Verdict.PUBLISH
        )
        worst = max(
            (b.verdict for b in blockers), key=lambda v: v.severity, default=Verdict.PUBLISH
        )
        return Decision(worst, blockers)


@dataclass(frozen=True, slots=True)
class SchemaRule:
    """Reject output that does not match the schema."""

    schema: Schema
    name: str = "schema"

    def check(self, context: GateContext) -> Sequence[Finding]:
        return [
            Finding(self.name, Verdict.REJECT, str(error))
            for error in self.schema.validate(context.output).errors
        ]


@dataclass(frozen=True, slots=True)
class CitationRule:
    """Reject output that cites unknown, malformed or out-of-force norms."""

    registry: NormRegistry
    field: str = "citations"
    name: str = "citations"

    def check(self, context: GateContext) -> Sequence[Finding]:
        report = verify_citations(context.output, self.registry, context.as_of, field=self.field)
        return [Finding(self.name, Verdict.REJECT, str(p)) for p in report.problems]


@dataclass(frozen=True, slots=True)
class NearMissRule:
    """Send output to review when a valid citation is one slip away from another valid id.

    The id exists and is in force, so :class:`CitationRule` is satisfied, but it
    may be a typo for its neighbour. See :func:`llm_gates.find_near_misses` for
    the exact criterion and its trade-off.
    """

    registry: NormRegistry
    field: str = "citations"
    max_edit_neighbours: int = DEFAULT_MAX_EDIT_NEIGHBOURS
    name: str = "near-miss"

    def check(self, context: GateContext) -> Sequence[Finding]:
        misses = find_near_misses(
            context.output,
            self.registry,
            context.as_of,
            field=self.field,
            max_edit_neighbours=self.max_edit_neighbours,
        )
        return [Finding(self.name, Verdict.REVIEW, str(miss)) for miss in misses]


@dataclass(frozen=True, slots=True)
class PiiRule:
    """Send output that looks like it contains personal data to review.

    The finding names the kind and location only, never the matched text, so
    reasons are safe to log.
    """

    name: str = "pii"

    def check(self, context: GateContext) -> Sequence[Finding]:
        return [
            Finding(self.name, Verdict.REVIEW, f"possible {hit.kind.value} at {hit.path}")
            for hit in find_pii(context.output)
        ]


@dataclass(frozen=True, slots=True)
class AgreementRule:
    """Send output to review unless an independent second opinion agrees.

    With ``required=True`` (the default) a missing second opinion is itself a
    reason for review. Remember that agreement measures similarity, not truth.
    """

    required: bool = True
    name: str = "agreement"

    def check(self, context: GateContext) -> Sequence[Finding]:
        if context.second_opinion is None:
            if not self.required:
                return []
            return [Finding(self.name, Verdict.REVIEW, "no second opinion provided")]
        agreement = compare_outputs(context.output, context.second_opinion)
        if agreement.level is AgreementLevel.AGREE:
            return []
        reasons = "; ".join(agreement.reasons)
        return [Finding(self.name, Verdict.REVIEW, f"models {agreement.level.value}: {reasons}")]
