"""The benchmark scores are reproducible, honest and never silently worse."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
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
    expected = run.render(results, run.load_snapshot())
    assert committed == expected, "run `python benchmarks/run.py` and commit"


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


# --- release snapshots and the before/after comparison ---------------------------------------


def test_snapshot_covers_exactly_the_dataset(run: ModuleType, results: Any) -> None:
    snapshot = run.load_snapshot()
    assert set(snapshot.predictions) == {case["id"] for case in results.cases}
    assert set(snapshot.category_hits) == {case["category"] for case in results.cases}


def test_snapshot_metrics_follow_from_its_predictions(run: ModuleType, results: Any) -> None:
    """The frozen numbers can be recomputed from the frozen decisions and the labels."""
    snapshot = run.load_snapshot()
    predictions = [snapshot.predictions[case["id"]] for case in results.cases]
    again = run.score("frozen", results.cases, predictions)
    assert snapshot.metrics["accuracy"] == pytest.approx(again.accuracy, abs=1e-6)
    assert snapshot.metrics["macro_f1"] == pytest.approx(again.macro_f1, abs=1e-6)
    assert snapshot.metrics["unsafe_publishes"] == again.unsafe_publishes
    assert snapshot.metrics["clean_blocked"] == again.clean_blocked


def test_snapshot_round_trip(
    run: ModuleType, results: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "HERE", tmp_path)
    taken = run.snapshot_from(results, "9.9.9")
    path = run.write_snapshot(taken)
    assert path == tmp_path / "release-9.9.9.json"
    assert run.load_snapshot("9.9.9") == taken


def test_snapshot_command(
    run: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(run, "HERE", tmp_path)
    assert run.main(["--snapshot"]) == 0
    assert f"wrote release-{run.__version__}.json" in capsys.readouterr().out
    assert (tmp_path / f"release-{run.__version__}.json").exists()


def _earlier_release(run: ModuleType, results: Any) -> Any:
    """An invented earlier release that differs from the gate on three cases."""
    cases, gate = results.cases, results.scores["gate"]
    now = run.snapshot_from(results, "0.0.2")
    predictions = dict(now.predictions)
    wrong = [i for i, c in enumerate(cases) if gate.predictions[i] != c["expected"]]
    right = [i for i, c in enumerate(cases) if gate.predictions[i] == c["expected"]]
    worse = wrong[0]
    fixed = next(i for i in right if cases[i]["category"] != cases[worse]["category"])
    shifted = wrong[1]

    def not_in(*avoid: str) -> str:
        label: str = next(label for label in run.CLASSES if label not in avoid)
        return label

    predictions[cases[fixed]["id"]] = not_in(cases[fixed]["expected"])
    predictions[cases[worse]["id"]] = cases[worse]["expected"]
    predictions[cases[shifted]["id"]] = not_in(
        gate.predictions[shifted], cases[shifted]["expected"]
    )
    hits = dict(now.category_hits)
    hits[cases[fixed]["category"]] -= 1
    hits[cases[worse]["category"]] += 1
    metrics = dict(now.metrics, accuracy=now.metrics["accuracy"] - 0.05)
    return run.Snapshot("0.0.1", metrics, hits, predictions)


def test_comparison_names_fixed_worse_and_shifted_cases(run: ModuleType, results: Any) -> None:
    previous = _earlier_release(run, results)
    text = "\n".join(run.render_comparison(results, previous, "0.0.2"))
    assert "## Before and after: 0.0.1 vs 0.0.2" in text
    assert "+5.0 pp" in text
    assert "(better)" in text
    assert "(worse)" in text
    assert "Cases whose decision changed since 0.0.1 (3):" in text
    for outcome in ("fixed", "now wrong", "still wrong, different decision"):
        assert f"| {outcome} |" in text


def test_comparison_is_skipped_for_the_same_version(run: ModuleType, results: Any) -> None:
    same = run.snapshot_from(results, run.__version__)
    assert "Before and after" not in run.render(results, same)
    assert "Before and after" not in run.render(results)


def test_comparison_change_formatting(run: ModuleType) -> None:
    assert run._change("accuracy", 0.5, 0.5) == "0"
    assert run._change("accuracy", 0.5, 0.55) == "+5.0 pp"
    assert run._change("unsafe_publishes", 10, 4) == "-6"
    assert run._change("clean_blocked", 4, 4) == "0"
