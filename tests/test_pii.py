from __future__ import annotations

import pytest

from llm_gates import PiiKind, find_pii


def kinds(value: object) -> list[PiiKind]:
    return [hit.kind for hit in find_pii(value)]


@pytest.mark.parametrize("text", ["write to jan.kowalski+news@example.co.uk now", "a@b.io"])
def test_email(text: str) -> None:
    assert kinds(text) == [PiiKind.EMAIL]


def test_email_text_and_span() -> None:
    (hit,) = find_pii("contact: jan@example.com.")
    assert hit.text == "jan@example.com"
    assert (hit.start, hit.end) == (9, 24)
    assert hit.path == "$"


@pytest.mark.parametrize(
    "text", ["call +48 123 456 789", "tel. 123-456-789", "123456789", "+48123456789"]
)
def test_phone(text: str) -> None:
    assert kinds(text) == [PiiKind.PHONE]


@pytest.mark.parametrize("text", ["order 1234567890123", "ref 12345678", "+48 12 34"])
def test_phone_ignores_other_digit_runs(text: str) -> None:
    assert kinds(text) == []


def test_valid_pesel_is_found() -> None:
    assert kinds("PESEL 44051401359") == [PiiKind.PESEL]


def test_pesel_with_bad_checksum_is_ignored() -> None:
    assert kinds("PESEL 44051401358") == []


def test_eleven_digits_inside_longer_number_are_ignored() -> None:
    assert kinds("144051401359") == []


def test_valid_iban_with_and_without_spaces() -> None:
    assert kinds("konto PL61 1090 1014 0000 0712 1981 2874") == [PiiKind.IBAN]
    assert kinds("DE89370400440532013000") == [PiiKind.IBAN]


def test_iban_with_bad_checksum_is_ignored() -> None:
    assert kinds("PL62 1090 1014 0000 0712 1981 2874") == []


@pytest.mark.parametrize(
    "text",
    ["ul. Marszałkowska 12/3", "mieszka przy ul. Jana Pawła II 5A w Warszawie", "Ul. Długa 7"],
)
def test_street_address(text: str) -> None:
    assert kinds(text) == [PiiKind.ADDRESS]


def test_ul_without_street_number_is_ignored() -> None:
    assert kinds("see ul. Długa") == []


def test_clean_text_has_no_hits() -> None:
    assert find_pii("The statute applies from 1 January 2024 to all vessels.") == []


def test_multiple_kinds_are_sorted_by_position() -> None:
    text = "ul. Długa 7, tel 123 456 789, a@b.pl"
    assert kinds(text) == [PiiKind.ADDRESS, PiiKind.PHONE, PiiKind.EMAIL]


def test_nested_values_report_their_path() -> None:
    value = {"summary": "ok", "people": [{"mail": "x@y.pl"}, "none"], "n": 5, "flag": None}
    (hit,) = find_pii(value)
    assert hit.path == "$.people[0].mail"
    assert hit.kind is PiiKind.EMAIL


def test_non_string_scalars_and_empty_containers_are_clean() -> None:
    assert find_pii(None) == []
    assert find_pii(123456789) == []
    assert find_pii({}) == []
    assert find_pii([]) == []


def test_dict_keys_are_not_scanned() -> None:
    assert find_pii({"jan@example.com": "value"}) == []


def test_iban_shaped_but_too_short_is_ignored() -> None:
    assert kinds("PL61 1090 1014") == []
