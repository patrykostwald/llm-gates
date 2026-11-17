"""Fact-checking claims extracted from an article, gated on their sources.

A model extracted claims from a news article and attached source ids. This
example shows how to write a custom rule: every claim must cite at least one
known source. Run it with ``python examples/news_claims.py``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date

from llm_gates import (
    Field,
    Finding,
    GateContext,
    PiiRule,
    PublicationGate,
    Schema,
    SchemaRule,
    Verdict,
)

KNOWN_SOURCES = {
    "stat-office-2025-q1": "National statistics office, Q1 2025 bulletin",
    "city-council-minutes": "City council minutes, 12 March 2025",
}

SCHEMA = Schema(
    {
        "claims": Field(
            list,
            min_items=1,
            items=Field(
                Schema(
                    {
                        "text": Field(str, min_length=1),
                        "sources": Field(list, items=Field(str)),
                    }
                )
            ),
        )
    }
)


class ClaimsNeedKnownSources:
    """Reject claims without a source, and claims citing a source we do not know."""

    name = "claim-sources"

    def check(self, context: GateContext) -> Sequence[Finding]:
        findings: list[Finding] = []
        claims = context.output.get("claims", [])
        for index, claim in enumerate(claims if isinstance(claims, list) else []):
            sources = claim.get("sources", []) if isinstance(claim, dict) else []
            if not sources:
                findings.append(Finding(self.name, Verdict.REJECT, f"claim {index} has no source"))
            findings.extend(
                Finding(self.name, Verdict.REJECT, f"claim {index} cites unknown source {s!r}")
                for s in sources
                if s not in KNOWN_SOURCES
            )
        return findings


ARTICLE_OK = """
{"claims": [
  {"text": "Unemployment fell to 4.1 percent in the first quarter.",
   "sources": ["stat-office-2025-q1"]},
  {"text": "The council approved the new tram line.",
   "sources": ["city-council-minutes"]}
]}
"""

ARTICLE_BAD = """
{"claims": [
  {"text": "Unemployment fell to 4.1 percent in the first quarter.",
   "sources": ["stat-office-2025-q1"]},
  {"text": "The mayor promised free public transport.", "sources": []},
  {"text": "Rents rose 30 percent.", "sources": ["someones-blog"]}
]}
"""


def main() -> None:
    gate = PublicationGate(
        [SchemaRule(SCHEMA), ClaimsNeedKnownSources(), PiiRule()],
    )
    for title, raw in (("Well sourced article", ARTICLE_OK), ("Weak article", ARTICLE_BAD)):
        decision = gate.evaluate(json.loads(raw), as_of=date(2025, 6, 1))
        print(f"{title}: {decision.verdict.value.upper()}")
        for reason in decision.reasons:
            print(f"  {reason}")


if __name__ == "__main__":
    main()
