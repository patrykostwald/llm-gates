"""Compare two independent outputs for the same question.

Typical use: ask two models from different providers, then check that they
reached the same conclusion on overlapping grounds.

.. important::
   Agreement measures **similarity, not correctness**. Two models can agree
   and both be wrong, especially when they share training data or the same
   misleading prompt. Treat disagreement as a reason to look closer, never
   agreement as proof.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgreementLevel(str, Enum):
    """How closely two outputs match."""

    AGREE = "agree"
    PARTIAL = "partial"
    DISAGREE = "disagree"


@dataclass(frozen=True, slots=True)
class Agreement:
    """Result of :func:`compare_outputs`."""

    level: AgreementLevel
    reasons: tuple[str, ...]
    conclusions_match: bool
    shared_citations: tuple[str, ...]
    only_in_a: tuple[str, ...]
    only_in_b: tuple[str, ...]
    citation_jaccard: float
    confidence_gap: float | None


def compare_outputs(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    *,
    conclusion_field: str = "conclusion",
    citations_field: str = "citations",
    confidence_field: str = "confidence",
    min_citation_jaccard: float = 0.5,
    max_confidence_gap: float = 0.3,
) -> Agreement:
    """Compare two outputs and grade their agreement.

    Rules, in order:

    * ``disagree``: the conclusions differ (or one is missing), or both cite
      something but share no citation at all.
    * ``partial``: same conclusion, but the Jaccard similarity of the citation
      sets is below ``min_citation_jaccard`` or the confidence values differ
      by more than ``max_confidence_gap``.
    * ``agree``: otherwise.

    Conclusions are compared case-insensitively with whitespace collapsed.
    Two empty citation sets have Jaccard similarity 1.0. Confidence is only
    compared when both outputs carry a numeric value.
    """
    reasons: list[str] = []

    conclusion_a = _normalize(a.get(conclusion_field))
    conclusion_b = _normalize(b.get(conclusion_field))
    conclusions_match = conclusion_a is not None and conclusion_a == conclusion_b
    if not conclusions_match:
        reasons.append(f"conclusions differ: {conclusion_a!r} vs {conclusion_b!r}")

    cites_a = _citation_set(a.get(citations_field))
    cites_b = _citation_set(b.get(citations_field))
    union = cites_a | cites_b
    jaccard = len(cites_a & cites_b) / len(union) if union else 1.0
    no_shared = bool(union) and not (cites_a & cites_b)
    if no_shared:
        reasons.append("no shared citations")
    elif jaccard < min_citation_jaccard:
        reasons.append(f"citation overlap {jaccard:.2f} is below {min_citation_jaccard:.2f}")

    gap = _confidence_gap(a.get(confidence_field), b.get(confidence_field))
    if gap is not None and gap > max_confidence_gap:
        reasons.append(f"confidence differs by {gap:.2f} (limit {max_confidence_gap:.2f})")

    if not conclusions_match or no_shared:
        level = AgreementLevel.DISAGREE
    elif reasons:
        level = AgreementLevel.PARTIAL
    else:
        level = AgreementLevel.AGREE

    return Agreement(
        level=level,
        reasons=tuple(reasons),
        conclusions_match=conclusions_match,
        shared_citations=tuple(sorted(cites_a & cites_b)),
        only_in_a=tuple(sorted(cites_a - cites_b)),
        only_in_b=tuple(sorted(cites_b - cites_a)),
        citation_jaccard=jaccard,
        confidence_gap=gap,
    )


def _normalize(conclusion: object) -> object:
    """Fold case and whitespace of strings; other values compare as they are."""
    if isinstance(conclusion, str):
        return " ".join(conclusion.split()).casefold() or None
    return conclusion


def _citation_set(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))


def _confidence_gap(a: object, b: object) -> float | None:
    numbers = [x for x in (a, b) if isinstance(x, int | float) and not isinstance(x, bool)]
    if len(numbers) != 2:
        return None
    return round(abs(numbers[0] - numbers[1]), 9)  # rounding keeps 0.8 - 0.5 within a 0.3 limit
