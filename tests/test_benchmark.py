"""The benchmark scores are reproducible, honest and never silently worse."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

Loader = Callable[[str], ModuleType]

# Categories in which the default gate is known to be wrong. Anything outside this
# set failing would be a regression in a rule, not a documented limitation.
KNOWN_GAP_CATEGORIES = {"clean", "typo_id", "pii_masked"}


@pytest.fixture(scope="module")
def run(bench: Loader) -> ModuleType:
    return bench("run")


@pytest.fixture(scope="module")
def results(run: ModuleType) -> object:
    return run.evaluate()


def test_scores_do_not_regress(run: ModuleType, results: Any) -> None:
    floor = run._read_baseline()
    assert run.regressions(results, floor) == []


def test_results_file_is_current(run: ModuleType, results: Any) -> None:
    committed = run.RESULTS_PATH.read_text(encoding="utf-8")
    assert committed == run.render(results), "run `python benchmarks/run.py` and commit"


def test_command_line_check_passes(run: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--check"]) == 0
    assert "benchmark ok" in capsys.readouterr().out


def test_gate_beats_both_baselines(results: Any) -> None:
    scores = results.scores
    gate = scores["gate"]
    for name in ("schema only", "agreement only"):
        other = scores[name]
        assert gate.accuracy > other.accuracy, name
        assert gate.macro_f1 > other.macro_f1, name
        assert gate.unsafe_publishes < other.unsafe_publishes, name


def test_baselines_behave_as_described(results: Any) -> None:
    scores = results.scores
    assert scores["agreement only"].classes["reject"].recall == 0.0  # it never rejects
    assert scores["schema only"].classes["review"].recall == 0.0  # it never asks a human


def test_gate_failures_are_all_documented(run: ModuleType, results: Any) -> None:
    scores = results.scores
    cases = results.cases
    wrong = {
        case["category"]
        for case, predicted in zip(cases, scores["gate"].predictions, strict=True)
        if predicted != case["expected"]
    }
    assert wrong <= KNOWN_GAP_CATEGORIES
    # and the gaps stay visible in the published results
    text = run.RESULTS_PATH.read_text(encoding="utf-8")
    assert "Where the gate is wrong" in text
    for category in wrong:
        assert f"`{category}`" in text


def test_scoring_arithmetic(run: ModuleType) -> None:
    cases = [{"expected": e} for e in ("publish", "publish", "review", "reject")]
    score = run.score("demo", cases, ["publish", "review", "publish", "reject"])
    assert score.accuracy == 0.5
    assert score.unsafe_publishes == 1
    assert score.clean_blocked == 1
    assert score.classes["publish"].precision == 0.5
    assert score.classes["publish"].recall == 0.5
    assert score.classes["review"].precision == 0.0
    assert score.classes["review"].recall == 0.0
    assert score.classes["reject"].f1 == 1.0


def test_precision_is_undefined_when_a_class_is_never_predicted(run: ModuleType) -> None:
    cases = [{"expected": e} for e in ("publish", "review")]
    score = run.score("demo", cases, ["publish", "publish"])
    assert score.classes["review"].precision is None
    assert score.classes["review"].f1 == 0.0


def test_regression_detection(run: ModuleType, results: Any) -> None:
    floor = run.baseline_from(results)
    assert run.regressions(results, floor) == []
    stricter = {**floor, "accuracy": floor["accuracy"] + 0.01, "max_unsafe_publishes": 0}
    problems = run.regressions(results, stricter)
    assert any(p.startswith("accuracy fell") for p in problems)
    assert any(p.startswith("max_unsafe_publishes rose") for p in problems)


def test_readme_table_matches_results(run: ModuleType, results: Any) -> None:
    readme = (run.HERE.parent / "README.md").read_text(encoding="utf-8")
    totals = results.scores["gate"].classes
    held_back = totals["review"].support + totals["reject"].support
    for score in results.scores.values():
        row = (
            f"| {run.pct(score.accuracy)} | {run.pct(score.publish_precision)} "
            f"| {score.unsafe_publishes} of {held_back} "
            f"| {score.clean_blocked} of {totals['publish'].support} |"
        )
        assert row in readme, f"README benchmark table is stale for {score.name}"
    assert f"{len(results.cases)} synthetic" in readme
