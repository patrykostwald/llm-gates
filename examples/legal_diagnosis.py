"""A legal-diagnosis assistant behind a publication gate.

The model reads a case description and cites provisions of a fictional statute,
the "Harbour Lighting Act 2019". The JSON below is what two different models
returned; nothing here calls a model. Run it with ``python examples/legal_diagnosis.py``.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from llm_gates import Field, NormRegistry, PublicationGate, Schema

# The statute: five articles. Article 5 was repealed at the end of 2023.
ACT = NormRegistry.from_records(
    [
        {"id": "HLA-1", "title": "Duty to show a light", "effective_from": "2019-03-01"},
        {"id": "HLA-2", "title": "Light colours", "effective_from": "2019-03-01"},
        {"id": "HLA-3", "title": "Inspection", "effective_from": "2019-03-01"},
        {"id": "HLA-4", "title": "Penalties", "effective_from": "2019-03-01"},
        {
            "id": "HLA-5",
            "title": "Transitional rules",
            "effective_from": "2019-03-01",
            "effective_to": "2023-12-31",
        },
    ]
)

SCHEMA = Schema(
    {
        "conclusion": Field(str, choices=("violation", "no_violation", "unclear")),
        "confidence": Field(float, minimum=0, maximum=1),
        "reasoning": Field(str, min_length=1),
        "citations": Field(list, items=Field(str), min_items=1),
    }
)

# What model A returned for: "A fishing boat sailed at night with no light on the mast."
MODEL_A = """
{
  "conclusion": "violation",
  "confidence": 0.9,
  "reasoning": "A vessel must show a light at night (HLA-1). A fine follows (HLA-4).",
  "citations": ["HLA-1", "HLA-4"]
}
"""

# What model B (another provider) returned for the same question.
MODEL_B = """
{
  "conclusion": "Violation",
  "confidence": 0.85,
  "reasoning": "The mast light is mandatory at night; the penalty clause applies.",
  "citations": ["HLA-1", "HLA-3", "HLA-4"]
}
"""

# A flawed answer: cites a repealed article and an article that does not exist.
MODEL_A_FLAWED = """
{
  "conclusion": "violation",
  "confidence": 0.95,
  "reasoning": "See the transitional rules (HLA-5) and article 9.",
  "citations": ["HLA-5", "HLA-9"]
}
"""

# An answer that leaks personal data.
MODEL_A_LEAKY = """
{
  "conclusion": "violation",
  "confidence": 0.9,
  "reasoning": "The skipper can be reached at skipper@example.com.",
  "citations": ["HLA-1"]
}
"""


def show(title: str, raw: str, second_raw: str | None, gate: PublicationGate) -> None:
    output: Any = json.loads(raw)
    second = json.loads(second_raw) if second_raw else None
    decision = gate.evaluate(output, as_of=date(2025, 6, 1), second_opinion=second)
    print(f"{title}: {decision.verdict.value.upper()}")
    for reason in decision.reasons:
        print(f"  {reason}")


def main() -> None:
    gate = PublicationGate.default(SCHEMA, ACT)
    show("Two models agree", MODEL_A, MODEL_B, gate)
    show("Repealed and unknown articles", MODEL_A_FLAWED, MODEL_B, gate)
    show("Personal data in the answer", MODEL_A_LEAKY, MODEL_B, gate)
    show("No second opinion", MODEL_A, None, gate)


if __name__ == "__main__":
    main()
