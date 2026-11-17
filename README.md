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
pip install "llm-gates @ git+https://github.com/patrykostwald/llm-gates@v0.2.0"
```

Not on PyPI. Drop the `@v0.2.0` to install the latest `main`.

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
| `NormRegistry`, `verify_citations`, `find_near_misses` | `citations` | Every cited id must exist and be in force on `as_of` (inclusive window). Problems are `unknown`, `not_in_force` or `malformed`. A valid id that is one swap of two characters (or, in a sparse registry, one edit) away from another id in force is a near miss. Load from JSON or CSV. |
| `compare_outputs` | `compare` | Compares two independent outputs: same conclusion, Jaccard overlap of citations, confidence gap. Returns `agree`, `partial` or `disagree` with reasons. |
| `find_pii` | `pii` | Finds e-mail (also `jan [at] example dot com`), phone, IBAN (mod-97, any spacing), PESEL (checksum, any spacing) and `ul.` street addresses. |
| `PublicationGate`, `Rule` | `gate` | Runs rules, takes the most severe verdict. Add your own rule by implementing `name` and `check(context)`. |

Default policy of `PublicationGate.default(...)`:

| Finding | Verdict |
| --- | --- |
| schema error, malformed, unknown or out-of-force citation | `reject` |
| valid citation that looks like a slip for another valid id (near miss) | `review` |
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
| `PublicationGate.default` | 89.3% | 91.2% | 3 of 156 | 19 of 50 |
| Schema validation only | 35.9% | 27.5% | 132 of 156 | 0 of 50 |
| Model agreement only | 32.0% | 30.3% | 115 of 156 | 0 of 50 |

*Unsafe publishes* are outputs that should have been held back but were published. Precision, recall, confusion matrices and per-category scores are in [`benchmarks/RESULTS.md`](benchmarks/RESULTS.md).

### Before and after: 0.1.1 vs 0.2.0

The 0.1.1 benchmark exposed two weaknesses. 0.2.0 addresses both. The same 206 cases, with the same labels, measure the effect:

| Metric | 0.1.1 | 0.2.0 | Change |
| --- | --- | --- | --- |
| Accuracy | 87.4% | 89.3% | +1.9 pp |
| Macro-F1 | 85.1% | 86.3% | +1.3 pp |
| Publish precision | 67.6% | 91.2% | +23.5 pp |
| Publish recall | 92.0% | 62.0% | -30.0 pp |
| Unsafe publishes | 22 of 156 | 3 of 156 | -19 |
| Clean cases blocked | 4 of 50 | 19 of 50 | +15 |

* **Masked personal data**: 16 of 16 published in 0.1.1, 3 of 16 in 0.2.0. The scanner now reads `jan [at] example dot com`, `jan(at)example.com`, PESEL numbers and IBANs split with spaces or hyphens, lower-case IBANs and 26-digit Polish account numbers.
* **Typos that land on another real norm** (`ACT-012` for `ACT-021`): 6 of 6 published in 0.1.1, 0 of 6 in 0.2.0. A new rule, `NearMissRule`, sends them to review.

This is a trade, not a free win. Fifteen more good answers now go to review, because six of the 24 norms in the benchmark registry have a swap twin and the dataset contains the same citations under opposite labels (`c001` and `c085`, for one), which no rule that reads only the citations can tell apart. Accuracy and precision rose; recall of good answers fell from 92% to 62%. The reasoning and the alternatives are in [ADR 0002](docs/adr/0002-near-miss-citations-go-to-review.md). If your ids are numbered so that many have a swap twin, leave the rule out with `PublicationGate.default(schema, registry, near_miss=False)`.

What still gets through, and why (every case is listed in `RESULTS.md`):

* 3 of 16 masked personal data samples: phone numbers in `(501) 113 129` form, spelled out in words (`five zero two ...`) or with the letter O for zero. The scanner has no detector for them; adding one risks flagging ordinary numbers. A fourth phone sample (`500.100.100`) is held back only because its citation happens to have a swap twin.
* Typos inside dense numbering (`ACT-012` written for `ACT-013`): not in the dataset and not caught, deliberately, since flagging them would flag every answer.
* 4 clean answers that are sent to review because a nine-digit reference looks like a phone number.

These numbers come from synthetic data written by the author, so read them as a regression guard and a comparison between approaches, not as a forecast for your traffic. CI fails if a score drops below the recorded floor. Reproduce with `python benchmarks/run.py --check`.

## Limitations

Read these before relying on the library.

* **Agreement is not accuracy.** Two models agreeing measures similarity of their answers. They can share training data, biases and the same mistake. A disagreement is a useful signal; an agreement is not proof.
* **A clean PII scan is not proof of anonymity.** The scanner is a tripwire for a few common formats. It does not find names, free-text descriptions, other countries' identifiers or most obfuscated data (it reads `jan [at] example dot com` and spaced PESEL and IBAN numbers, not spelled-out digits or dotted phone numbers), and it produces false positives (for example nine-digit numbers read as phones).
* **A citation check proves existence and validity, not relevance.** A norm can exist, be in force and still not support the claim. `llm-gates` does not read the cited text. The near-miss rule catches some mistyped ids (swapped characters, slips in sparse numbering), not a slip from `ACT-012` to `ACT-013` in consecutive numbering.
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

See [CONTRIBUTING.md](CONTRIBUTING.md). The reasoning behind the design is in [ADR 0001](docs/adr/0001-deterministic-gates-over-llm-as-judge.md) and [ADR 0002](docs/adr/0002-near-miss-citations-go-to-review.md).

## License

MIT, see [LICENSE](LICENSE).
