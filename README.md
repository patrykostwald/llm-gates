# llm-gates

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
pip install git+https://github.com/patrykostwald/llm-gates
```

Not on PyPI yet; a package release is on the roadmap.

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

## Limitations

Read these before relying on the library.

* **Agreement is not accuracy.** Two models agreeing measures similarity of their answers. They can share training data, biases and the same mistake. A disagreement is a useful signal; an agreement is not proof.
* **A clean PII scan is not proof of anonymity.** The scanner is a tripwire for a few common formats. It does not find names, free-text descriptions, other countries' identifiers or obfuscated data, and it produces false positives (for example nine-digit numbers read as phones).
* **A citation check proves existence and validity, not relevance.** A norm can exist, be in force and still not support the claim. `llm-gates` does not read the cited text.
* **The registry is your source of truth.** If it is incomplete or outdated, the gate is too.
* **Not legal advice.** The library is a building block, not a compliance product.

## Roadmap

* Citation locators below the norm level (paragraph, point) and norm versions.
* More PII detectors (national ID numbers, payment cards) behind a plugin interface.
* Async-friendly rule interface for checks that call out to a database.
* Optional JSON Schema import for the structural check.

## Development

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
ruff check . && mypy && pytest --cov
```

See [CONTRIBUTING.md](CONTRIBUTING.md). The reasoning behind the design is in [ADR 0001](docs/adr/0001-deterministic-gates-over-llm-as-judge.md).

## License

MIT, see [LICENSE](LICENSE).
