"""The benchmark dataset is deterministic, well formed and labelled independently of the gate."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import date
from types import ModuleType
from typing import Any

import pytest

from llm_gates import NormRegistry

Loader = Callable[[str], ModuleType]

CATEGORIES = {
    "clean",
    "repealed_norm",
    "unknown_norm",
    "typo_id",
    "date_boundary",
    "pii_explicit",
    "pii_masked",
    "second_opinion",
    "schema_error",
}


@pytest.fixture(scope="module")
def generate(bench: Loader) -> ModuleType:
    return bench("generate")


@pytest.fixture(scope="module")
def cases(generate: ModuleType) -> list[dict[str, Any]]:
    path = generate.CASES_PATH
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def registry(generate: ModuleType) -> NormRegistry:
    return NormRegistry.from_json(generate.REGISTRY_PATH)


def test_committed_files_match_the_generator(generate: ModuleType) -> None:
    records = generate.build_registry()
    expected_cases = generate.render_cases(generate.build_cases(records))
    assert generate.REGISTRY_PATH.read_text(encoding="utf-8") == generate.render_registry(records)
    assert generate.CASES_PATH.read_text(encoding="utf-8") == expected_cases


def test_generation_is_deterministic(generate: ModuleType) -> None:
    first = generate.build_cases(generate.build_registry())
    second = generate.build_cases(generate.build_registry())
    assert first == second


def test_size_categories_and_labels(cases: list[dict[str, Any]]) -> None:
    assert len(cases) >= 200
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["category"] for case in cases} == CATEGORIES
    assert {case["expected"] for case in cases} == {"publish", "review", "reject"}
    for case in cases:
        assert set(case) == {
            "id",
            "category",
            "expected",
            "as_of",
            "output",
            "second_opinion",
            "note",
        }
        date.fromisoformat(case["as_of"])


def test_every_category_has_enough_cases(cases: list[dict[str, Any]]) -> None:
    counts = Counter(case["category"] for case in cases)
    assert min(counts.values()) >= 16, counts


def test_data_is_plain_ascii(generate: ModuleType) -> None:
    for path in (generate.REGISTRY_PATH, generate.CASES_PATH):
        path.read_text(encoding="ascii")


def test_registry_design(registry: NormRegistry, generate: ModuleType) -> None:
    assert len(registry) == 40
    on = generate.AS_OF
    in_force = [
        norm for n in range(1, 41) if (norm := registry.get(f"ACT-{n:03d}")) and norm.in_force(on)
    ]
    assert {norm.id for norm in in_force} == set(generate.ACTIVE)


def _cited(case: dict[str, Any]) -> list[str]:
    return [c for c in case["output"]["citations"] if isinstance(c, str)]


def test_labels_follow_the_registry_not_the_gate(
    cases: list[dict[str, Any]], registry: NormRegistry
) -> None:
    """Re-derive the labels of the citation categories from the registry alone."""
    for case in cases:
        as_of = date.fromisoformat(case["as_of"])
        kind, label = case["category"], case["expected"]
        if kind in ("clean", "second_opinion", "pii_explicit", "pii_masked"):
            norms = [registry.get(c) for c in _cited(case)]
            assert all(n is not None and n.in_force(as_of) for n in norms), case["id"]
        elif kind == "repealed_norm":
            ended = [n for c in _cited(case) if (n := registry.get(c)) and not n.in_force(as_of)]
            assert ended and label == "reject", case["id"]
        elif kind == "unknown_norm":
            assert any(c not in registry for c in _cited(case)) and label == "reject", case["id"]
        elif kind == "typo_id" and label == "reject":
            assert any(c not in registry for c in _cited(case)), case["id"]
        elif kind == "typo_id":
            assert all(registry.get(c) is not None for c in _cited(case)), case["id"]
        elif kind == "date_boundary":
            norm = registry.get(_cited(case)[0])
            assert norm is not None
            assert norm.in_force(as_of) == (label == "publish"), case["id"]


def test_boundary_cases_probe_both_edges_of_each_window(cases: list[dict[str, Any]]) -> None:
    boundary = [c for c in cases if c["category"] == "date_boundary"]
    by_norm = Counter(c["output"]["citations"][0] for c in boundary)
    assert set(by_norm.values()) == {4}
    assert Counter(c["expected"] for c in boundary) == {"publish": 12, "reject": 12}
