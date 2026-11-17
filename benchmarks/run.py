"""Score the default gate and two naive baselines on the synthetic benchmark.

Systems compared on the same labelled cases:

* ``gate``: ``PublicationGate.default`` (schema, citations, PII, agreement).
* ``schema only``: publish whatever passes schema validation, reject the rest.
* ``agreement only``: an "LLM-as-judge proxy". Two models answered; publish when
  they agree, send everything else to review. It never rejects.

Usage::

    python benchmarks/run.py                    # rewrite benchmarks/RESULTS.md
    python benchmarks/run.py --check            # fail if RESULTS.md is stale or scores regress
    python benchmarks/run.py --update-baseline  # record the current scores as the floor
    python benchmarks/run.py --snapshot         # freeze the current scores as a release snapshot

The scoring is plain arithmetic on a fixed dataset, so the output is identical on
every run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from llm_gates import (
    AgreementLevel,
    Decision,
    Field,
    NormRegistry,
    PublicationGate,
    Schema,
    __version__,
    compare_outputs,
)

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE / "registry.json"
CASES_PATH = HERE / "cases.jsonl"
RESULTS_PATH = HERE / "RESULTS.md"
BASELINE_PATH = HERE / "baseline.json"
COMPARE_AGAINST = "0.1.1"
"""The release whose frozen snapshot the results are compared with."""

CLASSES = ("publish", "review", "reject")
SYSTEMS = ("gate", "schema only", "agreement only")
TOLERANCE = 1e-6

Case = dict[str, Any]


# --- loading -------------------------------------------------------------------------------


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def build_schema() -> Schema:
    """The structure every benchmark answer is expected to have."""
    return Schema(
        {
            "conclusion": Field(str, min_length=1),
            "confidence": Field(float, minimum=0, maximum=1),
            "citations": Field(list, items=Field(str), min_items=1),
            "summary": Field(str, required=False),
        }
    )


# --- the three systems -----------------------------------------------------------------------


def _second_opinion(case: Case) -> dict[str, Any] | None:
    second = case["second_opinion"]
    return second if isinstance(second, dict) else None


def run_gate(gate: PublicationGate, case: Case) -> Decision:
    return gate.evaluate(
        case["output"],
        as_of=date.fromisoformat(case["as_of"]),
        second_opinion=_second_opinion(case),
    )


def run_schema_only(schema: Schema, case: Case) -> str:
    return "publish" if schema.validate(case["output"]).ok else "reject"


def run_agreement_only(case: Case) -> str:
    output, second = case["output"], _second_opinion(case)
    if not isinstance(output, dict) or second is None:
        return "review"
    agreement = compare_outputs(output, second)
    return "publish" if agreement.level is AgreementLevel.AGREE else "review"


# --- metrics -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassScore:
    precision: float | None
    recall: float | None
    support: int

    @property
    def f1(self) -> float:
        p, r = self.precision or 0.0, self.recall or 0.0
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass(frozen=True)
class SystemScore:
    name: str
    predictions: tuple[str, ...]
    confusion: dict[str, dict[str, int]]
    classes: dict[str, ClassScore]
    accuracy: float
    macro_f1: float
    unsafe_publishes: int
    clean_blocked: int

    @property
    def publish_precision(self) -> float | None:
        return self.classes["publish"].precision

    @property
    def publish_recall(self) -> float | None:
        return self.classes["publish"].recall


def score(name: str, cases: Sequence[Case], predictions: Sequence[str]) -> SystemScore:
    confusion = {e: dict.fromkeys(CLASSES, 0) for e in CLASSES}
    for case, predicted in zip(cases, predictions, strict=True):
        confusion[case["expected"]][predicted] += 1
    classes: dict[str, ClassScore] = {}
    for label in CLASSES:
        true_positive = confusion[label][label]
        predicted_total = sum(confusion[e][label] for e in CLASSES)
        support = sum(confusion[label].values())
        classes[label] = ClassScore(
            precision=true_positive / predicted_total if predicted_total else None,
            recall=true_positive / support if support else None,
            support=support,
        )
    correct = sum(confusion[label][label] for label in CLASSES)
    return SystemScore(
        name=name,
        predictions=tuple(predictions),
        confusion=confusion,
        classes=classes,
        accuracy=correct / len(cases),
        macro_f1=sum(c.f1 for c in classes.values()) / len(CLASSES),
        unsafe_publishes=confusion["review"]["publish"] + confusion["reject"]["publish"],
        clean_blocked=confusion["publish"]["review"] + confusion["publish"]["reject"],
    )


@dataclass(frozen=True)
class Results:
    cases: tuple[Case, ...]
    scores: dict[str, SystemScore]
    gate_decisions: tuple[Decision, ...]


def evaluate(cases: Sequence[Case] | None = None) -> Results:
    cases = load_cases() if cases is None else cases
    registry = NormRegistry.from_json(REGISTRY_PATH)
    schema = build_schema()
    gate = PublicationGate.default(schema, registry)
    decisions = tuple(run_gate(gate, case) for case in cases)
    predictions: dict[str, list[str]] = {
        "gate": [d.verdict.value for d in decisions],
        "schema only": [run_schema_only(schema, c) for c in cases],
        "agreement only": [run_agreement_only(c) for c in cases],
    }
    scores = {name: score(name, cases, predictions[name]) for name in SYSTEMS}
    return Results(tuple(cases), scores, decisions)


# --- regression floor -------------------------------------------------------------------------


def baseline_from(results: Results) -> dict[str, float]:
    gate = results.scores["gate"]
    return {
        "accuracy": round(gate.accuracy, 6),
        "macro_f1": round(gate.macro_f1, 6),
        "publish_precision": round(gate.publish_precision or 0.0, 6),
        "review_recall": round(gate.classes["review"].recall or 0.0, 6),
        "reject_recall": round(gate.classes["reject"].recall or 0.0, 6),
        "max_unsafe_publishes": gate.unsafe_publishes,
        "max_clean_blocked": gate.clean_blocked,
    }


def regressions(results: Results, floor: dict[str, float]) -> list[str]:
    """Describe every metric that is worse than the recorded floor."""
    now = baseline_from(results)
    problems = [
        f"{key} fell from {floor[key]} to {now[key]}"
        for key in ("accuracy", "macro_f1", "publish_precision", "review_recall", "reject_recall")
        if now[key] + TOLERANCE < floor[key]
    ]
    problems += [
        f"{key} rose from {floor[key]} to {now[key]}"
        for key in ("max_unsafe_publishes", "max_clean_blocked")
        if now[key] > floor[key]
    ]
    return problems


# --- release snapshots ---------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """The gate's scores in a released version, frozen so later runs can compare with them."""

    version: str
    metrics: dict[str, float]
    category_hits: dict[str, int]
    predictions: dict[str, str]


METRIC_KEYS = (
    "accuracy",
    "macro_f1",
    "publish_precision",
    "publish_recall",
    "unsafe_publishes",
    "clean_blocked",
)


def snapshot_path(version: str) -> Path:
    return HERE / f"release-{version}.json"


def snapshot_from(results: Results, version: str) -> Snapshot:
    gate = results.scores["gate"]
    metrics = {
        "accuracy": round(gate.accuracy, 6),
        "macro_f1": round(gate.macro_f1, 6),
        "publish_precision": round(gate.publish_precision or 0.0, 6),
        "publish_recall": round(gate.publish_recall or 0.0, 6),
        "unsafe_publishes": gate.unsafe_publishes,
        "clean_blocked": gate.clean_blocked,
    }
    hits = {
        category: sum(
            1
            for case, predicted in zip(results.cases, gate.predictions, strict=True)
            if case["category"] == category and predicted == case["expected"]
        )
        for category in _category_order(results.cases)
    }
    predictions = {
        case["id"]: predicted
        for case, predicted in zip(results.cases, gate.predictions, strict=True)
    }
    return Snapshot(version, metrics, hits, predictions)


def write_snapshot(snapshot: Snapshot) -> Path:
    data = {
        "version": snapshot.version,
        "metrics": snapshot.metrics,
        "category_hits": snapshot.category_hits,
        "predictions": snapshot.predictions,
    }
    path = snapshot_path(snapshot.version)
    path.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    return path


def load_snapshot(version: str = COMPARE_AGAINST) -> Snapshot:
    data = json.loads(snapshot_path(version).read_text(encoding="utf-8"))
    return Snapshot(
        version=str(data["version"]),
        metrics={str(k): float(v) for k, v in data["metrics"].items()},
        category_hits={str(k): int(v) for k, v in data["category_hits"].items()},
        predictions={str(k): str(v) for k, v in data["predictions"].items()},
    )


# --- rendering -------------------------------------------------------------------------------


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def _category_order(cases: Sequence[Case]) -> list[str]:
    seen: dict[str, None] = {}
    for case in cases:
        seen.setdefault(case["category"], None)
    return list(seen)


def _why(decision: Decision) -> str:
    if not decision.blockers:
        return "no rule objected"
    return "; ".join(f"{b.rule}: {b.reason}" for b in decision.blockers[:2])


def _change(key: str, before: float, after: float) -> str:
    if key in ("unsafe_publishes", "clean_blocked"):
        return f"{int(after - before):+d}" if after != before else "0"
    return f"{(after - before) * 100:+.1f} pp" if abs(after - before) > TOLERANCE else "0"


def _metric_cell(key: str, value: float, results: Results) -> str:
    totals = {label: results.scores["gate"].classes[label].support for label in CLASSES}
    if key == "unsafe_publishes":
        return f"{int(value)} of {totals['review'] + totals['reject']}"
    if key == "clean_blocked":
        return f"{int(value)} of {totals['publish']}"
    return pct(value)


METRIC_LABELS = {
    "accuracy": "Accuracy",
    "macro_f1": "Macro-F1",
    "publish_precision": "Publish precision",
    "publish_recall": "Publish recall",
    "unsafe_publishes": "Unsafe publishes",
    "clean_blocked": "Clean cases blocked",
}


def comparison_rows(results: Results, previous: Snapshot, version: str) -> list[list[str]]:
    """Rows of the before and after table: metric, previous, current, change."""
    now = snapshot_from(results, version).metrics
    return [
        [
            METRIC_LABELS[key],
            _metric_cell(key, previous.metrics[key], results),
            _metric_cell(key, now[key], results),
            _change(key, previous.metrics[key], now[key]),
        ]
        for key in METRIC_KEYS
    ]


def render_comparison(results: Results, previous: Snapshot, version: str) -> list[str]:
    """The ``previous vs current`` section: totals, categories and every changed decision."""
    gate = results.scores["gate"]
    old, new = previous.version, version
    out = [
        f"## Before and after: {old} vs {new}",
        "",
        f"The same {len(results.cases)} cases with the same labels, scored by the default gate of "
        f"each release. The {old} column is a frozen snapshot of the tagged release "
        f"(`benchmarks/{snapshot_path(old).name}`); the {new} column is the code in this "
        "checkout.",
        "",
    ]
    out += _table(["Metric", old, new, "Change"], comparison_rows(results, previous, version))
    now = snapshot_from(results, version)
    rows = []
    for category in _category_order(results.cases):
        size = sum(1 for c in results.cases if c["category"] == category)
        before, after = previous.category_hits[category], now.category_hits[category]
        mark = "" if before == after else " (better)" if after > before else " (worse)"
        rows.append([f"`{category}`", size, f"{before}/{size}", f"{after}/{size}{mark}"])
    out += ["", "Correct decisions by category:", ""]
    out += _table(["Category", "Cases", old, new], rows)
    changed = []
    for case, decision in zip(results.cases, gate.predictions, strict=True):
        before_decision = previous.predictions[case["id"]]
        if before_decision == decision:
            continue
        if decision == case["expected"]:
            outcome = "fixed"
        elif before_decision == case["expected"]:
            outcome = "now wrong"
        else:
            outcome = "still wrong, different decision"
        changed.append(
            [
                case["id"],
                f"`{case['category']}`",
                case["expected"],
                before_decision,
                decision,
                outcome,
            ]
        )
    out += ["", f"Cases whose decision changed since {old} ({len(changed)}):", ""]
    out += _table(["Case", "Category", "Expected", old, new, "Outcome"], changed)
    out.append("")
    return out


def render(results: Results, previous: Snapshot | None = None) -> str:
    cases, scores = results.cases, results.scores
    gate = scores["gate"]
    totals = {label: gate.classes[label].support for label in CLASSES}
    out: list[str] = [
        "# Benchmark results",
        "",
        "Generated by `python benchmarks/run.py`. Do not edit by hand: CI fails when this file "
        "is out of date.",
        "",
        f"Dataset: {len(cases)} synthetic, labelled cases in {len(_category_order(cases))} "
        f"categories ({totals['publish']} should be published, {totals['review']} sent to "
        f"review, {totals['reject']} rejected). The norm registry, the people, the numbers and "
        "the answers are all fictional and generated by `benchmarks/generate.py`.",
        "",
        "## Summary",
        "",
        "**Unsafe publishes** are outputs that should have been held back but were published. "
        "**Clean cases blocked** are good outputs that were held back (extra work for a human). "
        "Publish precision is the share of published outputs that deserved it.",
        "",
    ]
    out += _table(
        [
            "System",
            "Accuracy",
            "Macro-F1",
            "Publish precision",
            "Publish recall",
            "Unsafe publishes",
            "Clean cases blocked",
        ],
        [
            [
                f"`{s.name}`" if s.name == "gate" else s.name,
                pct(s.accuracy),
                pct(s.macro_f1),
                pct(s.publish_precision),
                pct(s.publish_recall),
                f"{s.unsafe_publishes} of {totals['review'] + totals['reject']}",
                f"{s.clean_blocked} of {totals['publish']}",
            ]
            for s in scores.values()
        ],
    )
    out += [
        "",
        "`gate` is `PublicationGate.default`. `schema only` publishes anything that passes "
        "schema validation. `agreement only` is an LLM-as-judge proxy: publish when two models "
        "agree, review otherwise (macro-F1 treats an undefined precision as 0).",
        "",
    ]
    if previous is not None and previous.version != __version__:
        out += render_comparison(results, previous, __version__)
    out += ["## Precision and recall per decision", ""]
    rows = []
    for s in scores.values():
        for label in CLASSES:
            c = s.classes[label]
            rows.append([s.name, label, pct(c.precision), pct(c.recall), pct(c.f1), c.support])
    out += _table(["System", "Decision", "Precision", "Recall", "F1", "Cases"], rows)
    out += [
        "",
        "## Confusion matrices",
        "",
        "Rows are the expected decision, columns the actual one.",
        "",
    ]
    for s in scores.values():
        out += [f"**{s.name}**", ""]
        matrix = [[label, *(s.confusion[label][p] for p in CLASSES)] for label in CLASSES]
        out += _table(["expected \\ actual", *CLASSES], matrix)
        out.append("")
    out += ["## Accuracy by category", ""]
    category_rows = []
    for category in _category_order(cases):
        indexes = [i for i, c in enumerate(cases) if c["category"] == category]
        expected = sorted({cases[i]["expected"] for i in indexes})
        row: list[object] = [f"`{category}`", len(indexes), "/".join(expected)]
        for s in scores.values():
            hits = sum(1 for i in indexes if s.predictions[i] == cases[i]["expected"])
            row.append(f"{hits}/{len(indexes)}")
        category_rows.append(row)
    out += _table(["Category", "Cases", "Expected", *SYSTEMS], category_rows)
    out += ["", "## Where the gate is wrong", ""]
    wrong = [
        (c, d, p)
        for c, d, p in zip(cases, results.gate_decisions, gate.predictions, strict=True)
        if p != c["expected"]
    ]
    out += [
        f"The default gate disagrees with the label on {len(wrong)} of {len(cases)} cases. "
        "Every one is listed, nothing is hidden.",
        "",
    ]
    out += _table(
        ["Case", "Category", "Expected", "Gate said", "Why", "What the case is"],
        [
            [c["id"], f"`{c['category']}`", c["expected"], p, _why(d), c["note"]]
            for c, d, p in wrong
        ],
    )
    out += ["", *LIMITATIONS]
    return "\n".join(out) + "\n"


LIMITATIONS = [
    "## Limitations of this benchmark",
    "",
    "Read the numbers with these caveats.",
    "",
    "* **The data is synthetic and written by the author of the gate.** It exercises the "
    "documented behaviour of each rule. It does not estimate how often a real model makes these "
    "mistakes, and it is not a measure of performance on real traffic. About three quarters of "
    "the cases are bad on purpose, so absolute accuracy says little; the comparison between "
    "systems on the same cases says more.",
    "* **Perfect `reject` scores are expected, not impressive.** The `reject` labels are defined "
    "by the same registry and schema logic the gate implements, so the gate agrees with them by "
    "construction. They show that the rules do what they say, not that they generalise.",
    "* **The masked PII cases are chosen because a naive pattern scanner misses them.** The "
    "scanner reads masked e-mail addresses (`jan [at] example dot com`), PESEL numbers and IBANs "
    "split with spaces or hyphens and 26-digit Polish account numbers. Phone numbers written "
    "with dots or parentheses, with spelled-out digits or with the letter O for zero are still "
    "not recognised. This is documented in `llm_gates.pii`. Real leaks are more varied than "
    "these samples.",
    "* **A typo that lands on another real norm in force is caught only in two cases, and "
    "it costs false alarms.** `NearMissRule` (0.2.0) sends an answer to review when a cited id "
    "is a swap of two adjacent characters away from another norm in force (`ACT-012` and "
    "`ACT-021`), or one edit away in a registry where that is unusual. It holds back every "
    "near-miss case here, and it also holds back good answers whose citation happens to have a "
    "swap twin. The dataset even contains the same citations twice with opposite labels (c001 "
    "and c085, c022 and c089, c026 and c088), so no rule that looks only at the citations can "
    "be right on both. Dense numbering is deliberately not flagged: a slip from `ACT-012` to "
    "`ACT-013` still passes. See ADR 0002.",
    "* **One masked phone case is held back by accident.** c146 is sent to review because its "
    "citation has a swap twin, not because the scanner recognised the phone number.",
    "* **Digits that look like a phone number are flagged.** Clean text containing a nine-digit "
    "reference goes to review. The scanner prefers a false alarm to a silent miss.",
    "* **Agreement is not accuracy.** In the norm-error categories the second model repeats "
    "the first model's mistake in three cases out of four (every fourth case it disagrees), as "
    "correlated models do. That is why `agreement only` publishes so many bad outputs. A "
    "real second opinion could be more or less correlated than this; either way it would not "
    "check facts.",
    '* **Labels encode a policy.** `reject` means "provably wrong against the registry or '
    'schema" and `review` means "a human should look". Other teams may draw the lines '
    "differently, and every case is in `benchmarks/cases.jsonl` for you to re-label.",
    "",
    "## Reproduce",
    "",
    "```",
    "python benchmarks/generate.py   # rewrite the dataset (deterministic)",
    "python benchmarks/run.py        # rewrite this file",
    "python benchmarks/run.py --check",
    "```",
    "",
    "`tests/test_benchmark.py` runs the check in CI, so scores cannot get worse unnoticed. "
    "Improving a score means rerunning `python benchmarks/run.py --update-baseline` in the same "
    "commit.",
]


# --- command line --------------------------------------------------------------------------------


def _read_baseline(path: Path = BASELINE_PATH) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in data.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    parser.add_argument(
        "--update-baseline", action="store_true", help="record current scores as the floor"
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="freeze the current gate scores as benchmarks/release-<version>.json",
    )
    args = parser.parse_args(argv)

    results = evaluate()
    if args.snapshot:
        print(f"wrote {write_snapshot(snapshot_from(results, __version__)).name}")
        return 0
    if args.update_baseline:
        text = json.dumps(baseline_from(results), indent=2) + "\n"
        BASELINE_PATH.write_bytes(text.encode("utf-8"))
        print(f"wrote {BASELINE_PATH.name}")
    markdown = render(results, load_snapshot())
    if args.check:
        problems = regressions(results, _read_baseline())
        current = RESULTS_PATH.read_text(encoding="utf-8") if RESULTS_PATH.exists() else ""
        if current != markdown:
            problems.append("RESULTS.md is out of date; run `python benchmarks/run.py`")
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        if not problems:
            print("benchmark ok")
        return 1 if problems else 0
    RESULTS_PATH.write_bytes(markdown.encode("utf-8"))
    print(f"wrote {RESULTS_PATH.name}")
    for s in results.scores.values():
        print(f"{s.name:>15}: accuracy {pct(s.accuracy)}, unsafe publishes {s.unsafe_publishes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
