from __future__ import annotations

import time

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


# --- masked and spaced values --------------------------------------------------------------

PESEL = "44051401359"
IBAN = "PL61109010140000071219812874"


def with_check_digit(body: str) -> str:
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return body + str((10 - sum(int(d) * w for d, w in zip(body, weights, strict=True)) % 10) % 10)


@pytest.mark.parametrize(
    "masked",
    [
        "jan [at] example dot com",
        "jan(at)example.com",
        "jan.lis(at)example(dot)org",
        "jan AT example DOT com",
        "jan {at} example [dot] co [dot] uk",
        "jan <at> example.com",
        "jan [@] example.com",
        "jan[at]example[dot]com",
        "jan at example dot com",
        "jan.lis+news at sub dot example dot net",
    ],
)
def test_masked_email(masked: str) -> None:
    (hit,) = find_pii(f"Contact detail on file: {masked}.")
    assert hit.kind is PiiKind.EMAIL
    assert hit.text.startswith("jan")
    assert hit.text.rstrip(".").endswith(("com", "org", "uk", "net"))


def test_masked_email_span_stops_at_the_end_of_the_address() -> None:
    text = "write to jan [at] example dot com today"
    (hit,) = find_pii(text)
    assert hit.text == "jan [at] example dot com"
    assert text[hit.start : hit.end] == hit.text


@pytest.mark.parametrize(
    "prose",
    [
        "Look at example.com for details.",
        "The meeting is at noon.",
        "She arrived at the site dot com later.",
        "Both rules apply (at least in part).",
        "Ticket [at] the door costs more.",
        "The dot product at hand.",
        "an address like jan at home",
    ],
)
def test_prose_with_at_and_dot_is_not_an_email(prose: str) -> None:
    assert find_pii(prose) == []


@pytest.mark.parametrize(
    "spaced",
    [
        "440514 01359",
        "44 05 14 01 359",
        "440514-01359",
        "4405 1401 359",
        "44  05  14  01  359",
        "44 - 05 - 14 - 01 - 359",
        "44\u00a005\u00a014\u00a001\u00a0359",
    ],
)
def test_spaced_pesel(spaced: str) -> None:
    (hit,) = find_pii(f"Identification on file: {spaced}.")
    assert hit.kind is PiiKind.PESEL
    assert hit.text == spaced


def test_spaced_pesel_needs_a_valid_checksum() -> None:
    assert find_pii("Identification on file: 44 05 14 01 358.") == []


def test_spaced_pesel_needs_a_plausible_date() -> None:
    month_14 = with_check_digit("4414010135")
    assert find_pii(month_14[:6] + " " + month_14[6:]) == []
    day_00 = with_check_digit("4405000135")
    assert find_pii(day_00[:6] + " " + day_00[6:]) == []
    assert kinds(month_14) == [PiiKind.PESEL]  # an unspaced run is judged by checksum alone


def test_spaced_pesel_inside_longer_digit_runs_is_ignored() -> None:
    assert find_pii("1234 5678 9012 3456") == []
    assert find_pii("44 05 14 01 3590") == []


def test_spaced_pesel_may_be_followed_by_another_number() -> None:
    (hit,) = find_pii("44 05 14 01 359 2024")
    assert hit.text == "44 05 14 01 359"


def test_phone_with_country_code_is_not_read_as_a_pesel() -> None:
    phone_like = with_check_digit("48" + "05140135")  # "+48" and nine digits, a valid PESEL shape
    text = f"call +{phone_like[:2]} {phone_like[2:5]} {phone_like[5:8]} {phone_like[8:]}"
    assert kinds(text) == [PiiKind.PHONE]


@pytest.mark.parametrize(
    "spaced",
    [
        "PL61 1090 1014 0000 0712 1981 2874",
        "pl61 1090 1014 0000 0712 1981 2874",
        "PL61-1090-1014-0000-0712-1981-2874",
        "PL 61 1090 1014 0000 0712 1981 2874",
        "PL611090 1014 00000712 19812874",
        "PL61  1090  1014  0000  0712  1981  2874",
        "PL61\u00a01090\u00a01014\u00a00000\u00a00712\u00a01981\u00a02874",
        "pl61109010140000071219812874",
    ],
)
def test_masked_iban(spaced: str) -> None:
    (hit,) = find_pii(f"Account on file: {spaced}.")
    assert hit.kind is PiiKind.IBAN
    assert hit.text == spaced


def test_iban_span_does_not_swallow_following_words() -> None:
    (hit,) = find_pii("account PL61 1090 1014 0000 0712 1981 2874 and more words")
    assert hit.text == "PL61 1090 1014 0000 0712 1981 2874"


@pytest.mark.parametrize(
    "iban", ["GB82 WEST 1234 5698 7654 32", "FR14 2004 1010 0505 0001 3M02 606"]
)
def test_ibans_with_letters_and_other_countries(iban: str) -> None:
    assert kinds(f"IBAN {iban}") == [PiiKind.IBAN]


@pytest.mark.parametrize(
    "text",
    [
        "XX61 1090 1014 0000 0712 1981 2874",  # unknown country
        "PL61 1090 1014 0000 0712 1981 287",  # too short for Poland
        "is 12 apples and 3 pears and 5 plums",
        "to 15 of the 20 pending cases",
        "pl62 1090 1014 0000 0712 1981 2874",  # bad checksum
    ],
)
def test_iban_lookalikes(text: str) -> None:
    assert PiiKind.IBAN not in kinds(text)


def test_polish_account_number_without_country_prefix() -> None:
    assert kinds("konto 61 1090 1014 0000 0712 1981 2874") == [PiiKind.IBAN]
    assert kinds("konto 61109010140000071219812874") == [PiiKind.IBAN]
    assert kinds("konto 61-1090-1014-0000-0712-1981-2874") == [PiiKind.IBAN]


def test_polish_account_number_must_pass_the_checksum_and_have_26_digits() -> None:
    assert find_pii("konto 62 1090 1014 0000 0712 1981 2874") == []
    assert find_pii("konto 61 1090 1014 0000 0712 1981 28745") == []
    assert find_pii("konto 61 1090 1014 0000 0712 1981 287") == []


def test_runs_stop_at_other_punctuation_and_at_the_end_of_the_text() -> None:
    assert kinds("PL61 1090 1014 0000 0712 1981 2874") == [PiiKind.IBAN]
    assert kinds("(PL61 1090 1014 0000 0712 1981 2874)") == [PiiKind.IBAN]
    assert kinds("PL61 1090 1014 0000 0712,1981 2874") == []


def test_scanning_long_hostile_input_stays_fast() -> None:
    hostile = [
        "a" * 200_000,
        "1" + " " * 100_000 + "2",
        "1 " * 50_000,
        "a [at] " * 20_000,
        "a at b dot " * 20_000,
        ("PL61 " + "1090 " * 20) * 2_000,
        "-" * 100_000,
    ]
    started = time.perf_counter()
    for text in hostile:
        find_pii(text)
    assert time.perf_counter() - started < 20
