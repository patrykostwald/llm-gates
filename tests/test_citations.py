from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from llm_gates import Norm, NormRegistry, ProblemKind, RegistryError, verify_citations

REGISTRY = NormRegistry(
    [
        Norm("open", "Open ended", date(2020, 1, 1)),
        Norm("closed", "Window", date(2020, 1, 1), date(2020, 12, 31)),
    ]
)


def kinds(output: dict[str, object], as_of: date) -> list[ProblemKind]:
    return [p.kind for p in verify_citations(output, REGISTRY, as_of).problems]


def test_known_norm_in_force_is_ok() -> None:
    report = verify_citations({"citations": ["open", "closed"]}, REGISTRY, date(2020, 6, 1))
    assert report.ok
    assert report.checked == 2


def test_validity_window_is_inclusive_on_both_ends() -> None:
    assert kinds({"citations": ["closed"]}, date(2020, 1, 1)) == []
    assert kinds({"citations": ["closed"]}, date(2020, 12, 31)) == []


def test_day_before_start_and_after_end_are_not_in_force() -> None:
    assert kinds({"citations": ["closed"]}, date(2019, 12, 31)) == [ProblemKind.NOT_IN_FORCE]
    assert kinds({"citations": ["closed"]}, date(2021, 1, 1)) == [ProblemKind.NOT_IN_FORCE]


def test_open_ended_norm_stays_in_force() -> None:
    assert kinds({"citations": ["open"]}, date(2999, 1, 1)) == []


def test_unknown_norm() -> None:
    report = verify_citations({"citations": ["ghost"]}, REGISTRY, date(2020, 6, 1))
    assert [str(p) for p in report.problems] == ["unknown: ghost is not in the registry"]


@pytest.mark.parametrize("entry", ["", "   ", "two words", 7, None, ["open"]])
def test_malformed_entries(entry: object) -> None:
    assert kinds({"citations": [entry]}, date(2020, 6, 1)) == [ProblemKind.MALFORMED]


def test_empty_and_missing_citation_lists_are_clean() -> None:
    assert verify_citations({"citations": []}, REGISTRY, date(2020, 6, 1)).ok
    report = verify_citations({}, REGISTRY, date(2020, 6, 1))
    assert report.ok
    assert report.checked == 0


def test_citations_field_must_be_a_list() -> None:
    report = verify_citations({"citations": "open"}, REGISTRY, date(2020, 6, 1))
    assert [p.kind for p in report.problems] == [ProblemKind.MALFORMED]


def test_custom_field_name_and_multiple_problems() -> None:
    output = {"refs": ["open", "ghost", "closed", ""]}
    report = verify_citations(output, REGISTRY, date(2021, 6, 1), field="refs")
    assert [p.kind for p in report.problems] == [
        ProblemKind.UNKNOWN,
        ProblemKind.NOT_IN_FORCE,
        ProblemKind.MALFORMED,
    ]
    assert report.checked == 4


def test_norm_rejects_reversed_window_and_bad_id() -> None:
    with pytest.raises(RegistryError, match="ends before"):
        Norm("x", "t", date(2020, 2, 1), date(2020, 1, 1))
    with pytest.raises(RegistryError, match="invalid norm id"):
        Norm("has space", "t", date(2020, 1, 1))


def test_registry_basics() -> None:
    assert len(REGISTRY) == 2
    assert "open" in REGISTRY
    assert "ghost" not in REGISTRY
    assert REGISTRY.get("ghost") is None
    with pytest.raises(RegistryError, match="duplicate"):
        REGISTRY.add(Norm("open", "again", date(2021, 1, 1)))


def test_from_records_parses_dates_and_blank_end() -> None:
    registry = NormRegistry.from_records(
        [
            {"id": " a ", "title": "A", "effective_from": "2020-01-01", "effective_to": ""},
            {
                "id": "b",
                "title": "B",
                "effective_from": "2020-01-01",
                "effective_to": "2020-02-01",
            },
            {"id": "c", "title": "C", "effective_from": "2020-01-01", "effective_to": None},
        ]
    )
    assert registry.get("a") == Norm("a", "A", date(2020, 1, 1))
    assert registry.get("b") == Norm("b", "B", date(2020, 1, 1), date(2020, 2, 1))
    assert registry.get("c") is not None


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"title": "t", "effective_from": "2020-01-01"}, "missing 'id'"),
        ({"id": "a", "title": "t"}, "missing 'effective_from'"),
        ({"id": "a", "title": "t", "effective_from": "01/02/2020"}, "invalid date"),
        (
            {"id": "a", "title": "t", "effective_from": "2020-01-01", "effective_to": "soon"},
            "invalid date",
        ),
    ],
)
def test_from_records_rejects_bad_records(record: dict[str, str], message: str) -> None:
    with pytest.raises(RegistryError, match=message):
        NormRegistry.from_records([record])


def test_load_from_json_file(tmp_path: Path) -> None:
    path = tmp_path / "norms.json"
    path.write_text(
        '[{"id": "n1", "title": "Zażółć", "effective_from": "2020-01-01", "effective_to": null}]',
        encoding="utf-8",
    )
    registry = NormRegistry.from_json(path)
    norm = registry.get("n1")
    assert norm is not None
    assert norm.title == "Zażółć"


def test_json_registry_must_be_a_list(tmp_path: Path) -> None:
    path = tmp_path / "norms.json"
    path.write_text('{"id": "n1"}', encoding="utf-8")
    with pytest.raises(RegistryError, match="list of objects"):
        NormRegistry.from_json(path)


def test_load_from_csv_file(tmp_path: Path) -> None:
    path = tmp_path / "norms.csv"
    path.write_text(
        "id,title,effective_from,effective_to\n"
        "n1,First,2020-01-01,2020-12-31\n"
        "n2,Second,2021-01-01,\n",
        encoding="utf-8",
    )
    registry = NormRegistry.from_csv(str(path))
    assert len(registry) == 2
    second = registry.get("n2")
    assert second is not None
    assert second.effective_to is None
