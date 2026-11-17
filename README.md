# llm-gates

[![CI](https://github.com/patrykostwald/llm-gates/actions/workflows/ci.yml/badge.svg)](https://github.com/patrykostwald/llm-gates/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)

**Models propose, code decides.**

Deterministic gates for structured LLM output. Zero runtime dependencies, standard library only, Python 3.10+.

## The problem

A language model can return perfectly formatted JSON that is still wrong: a statute that was repealed last year, a citation that never existed, an e-mail address that slipped into the summary. Asking another model whether the first one is right just moves the problem, because the judge can be wrong in the same way.

## The idea

Put the model's output through small, deterministic checks before anyone sees it. Each check is plain code: the same input always gives the same answer, and every refusal comes with a reason you can read, log and test.

```
model output (JSON) -> schema -> citations -> PII scan -> second opinion -> publish | review | reject
```

* `reject`: something is definitely wrong (broken schema, cited norm does not exist).
* `review`: something needs a human (possible personal data, the second model disagrees).
* `publish`: every rule is clean.

## Install

```
pip install "llm-gates @ git+https://github.com/patrykostwald/llm-gates@v0.1.1"
```

Not on PyPI. Drop the `@v0.1.1` to install the latest `main`.

From a checkout: `pip install -e ".[dev]"`.

## Thirty seconds

```python
from datetime import date

from llm_gates import Field, NormRegistry, PublicationGate, Schema

schema = Schema(
    {
        "conclusion": Field(str),
        "confidence": Field(float, minimum=0, maximum=1),
        "citations": Field(list, items=Field(str), min_items=1),
    }
)
registry = NormRegistry.from_records(
    [
        {"id": "ACT-1", "title": "Duty of care", "effective_from": "2020-01-01"},
        {
            "id": "ACT-2",
            "title": "Repealed rule",
            "effective_from": "2020-01-01",
            "effective_to": "2022-12-31",
        },
    ]
)
gate = PublicationGate.default(schema, registry)

answer = {"conclusion": "liable", "confidence": 0.8, "citations": ["ACT-1", "ACT-2"]}
decision = gate.evaluate(answer, as_of=date(2025, 6, 1), second_opinion=answer)

print(decision.verdict.value)  # reject
for reason in decision.reasons:
    print(reason)  # [reject] citations: not_in_force: ACT-2 is not in force on 2025-06-01
```

Two runnable examples live in [`examples/`](examples): `legal_diagnosis.py` (a fictional statute, two model answers) and `news_claims.py` (claims and sources, with a custom rule).

## Concepts

| Piece | Module | What it does |
| --- | --- | --- |
| `Schema`, `Field` | `schema` | Validates structure: required fields, types, allowed values, bounds, lists, nested objects. Errors carry a path such as `$.citations[2]`. |
| `NormRegistry`, `verify_citations` | `citations` | Every cited id must exist and be in force on `as_of` (inclusive window). Problems are `unknown`, `not_in_force` or `malformed`. Load from JSON or CSV. |
| `compare_outputs` | `compare` | Compares two independent outputs: same conclusion, Jaccard overlap of citations, confidence gap. Returns `agree`, `partial` or `disagree` with reasons. |
| `find_pii` | `pii` | Finds e-mail, phone, IBAN (mod-97), PESEL (checksum) and `ul.` street addresses. |
| `PublicationGate`, `Rule` | `gate` | Runs rules, takes the most severe verdict. Add your own rule by implementing `name` and `check(context)`. |

Default policy of `PublicationGate.default(...)`:

| Finding | Verdict |
| --- | --- |
| schema error, malformed, unknown or out-of-force citation | `reject` |
| possible personal data | `review` |
| second opinion missing, partial or disagreeing | `review` |
| nothing found | `publish` |

Write a rule in a few lines:

```python
class NoGuarantees:
    name = "no-guarantees"

    def check(self, context):
        if "guarantee" in str(context.output.get("conclusion", "")):
            return [Finding(self.name, Verdict.REVIEW, "promises a guarantee")]
        return []


gate.add_rule(NoGuarantees())
```

## Benchmark

Claims are cheap, so the repository measures them. `benchmarks/` holds 206 synthetic, labelled cases (a fictional register of norms with validity dates, plus clean, repealed, unknown and mistyped citations, validity-window edges, explicit and masked personal data, second-opinion agreement and schema errors). Each case has an expected decision: `publish`, `review` or `reject`. The default gate is scored next to two naive baselines: schema validation alone, and agreement between two models alone (an LLM-as-judge proxy that can only publish or ask for review).

| System | Accuracy | Publish precision | Unsafe publishes | Clean cases blocked |
| --- | --- | --- | --- | --- |
| `PublicationGate.default` | 87.4% | 67.6% | 22 of 156 | 4 of 50 |
| Schema validation only | 35.9% | 27.5% | 132 of 156 | 0 of 50 |
| Model agreement only | 32.0% | 30.3% | 115 of 156 | 0 of 50 |

*Unsafe publishes* are outputs that should have been held back but were published. Precision, recall, confusion matrices and per-category scores are in [`benchmarks/RESULTS.md`](benchmarks/RESULTS.md).

What the gate does not catch is listed there case by case:

* 16 of 16 masked personal data samples ("jan [at] example dot com", a PESEL with spaces) are published.
* 6 of 6 id typos that land on another real norm in force are published.
* 4 clean answers are sent to review because a nine-digit reference looks like a phone number.

These numbers come from synthetic data written by the author, so read them as a regression guard and a comparison between approaches, not as a forecast for your traffic. CI fails if a score drops. Reproduce with `python benchmarks/run.py --check`.

## Limitations

Read these before relying on the library.

* **Agreement is not accuracy.** Two models agreeing measures similarity of their answers. They can share training data, biases and the same mistake. A disagreement is a useful signal; an agreement is not proof.
* **A clean PII scan is not proof of anonymity.** The scanner is a tripwire for a few common formats. It does not find names, free-text descriptions, other countries' identifiers or obfuscated data, and it produces false positives (for example nine-digit numbers read as phones).
* **A citation check proves existence and validity, not relevance.** A norm can exist, be in force and still not support the claim. `llm-gates` does not read the cited text.
* **The registry is your source of truth.** If it is incomplete or outdated, the gate is too.
* **Not legal advice.** The library is a building block, not a compliance product.

## Roadmap

Tracked as [issues](https://github.com/patrykostwald/llm-gates/issues):

* [#1](https://github.com/patrykostwald/llm-gates/issues/1) PII detectors for other EU countries (good first issue).
* [#2](https://github.com/patrykostwald/llm-gates/issues/2) Import JSON Schema for the structural check.
* [#3](https://github.com/patrykostwald/llm-gates/issues/3) Citation locators below the norm level (article, paragraph) and norm versions.
* [#4](https://github.com/patrykostwald/llm-gates/issues/4) Optional adapters for provider structured-output APIs.

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
ruff check . && mypy && pytest --cov
python benchmarks/run.py --check
```

See [CONTRIBUTING.md](CONTRIBUTING.md). The reasoning behind the design is in [ADR 0001](docs/adr/0001-deterministic-gates-over-llm-as-judge.md).

## License

MIT, see [LICENSE](LICENSE).
