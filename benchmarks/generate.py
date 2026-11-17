"""Generate the synthetic benchmark dataset (``registry.json`` and ``cases.jsonl``).

Everything here is fictional and deterministic: no randomness, no clock, no
network. Cases are derived from their index with plain arithmetic, so running
this script twice (or on another machine, or on another Python version)
produces byte-identical data.

The module deliberately does not import ``llm_gates``. The expected decision of
each case is decided by the design of the case, never by looking at what the
gate answers.

Run ``python benchmarks/generate.py`` to rewrite the data files.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE / "registry.json"
CASES_PATH = HERE / "cases.jsonl"

AS_OF = date(2026, 6, 15)
"""The date used by every case unless it tests a validity boundary."""

TOPICS = [
    "Duty of care",
    "Data retention",
    "Product labelling",
    "Safe storage",
    "Fair notice",
    "Contract withdrawal",
    "Tenant deposits",
    "Public tenders",
    "Noise limits",
    "Waste handling",
    "Import licensing",
    "Advertising claims",
    "Records access",
    "Event permits",
    "Boat registration",
    "Seed certification",
    "Library lending",
    "Market stalls",
    "Pet registration",
    "Fire inspection",
    "Parking zones",
    "Gift vouchers",
    "Ferry timetables",
    "Window displays",
    "Grain storage",
    "Kiosk licences",
    "Harbour dues",
    "Street trading",
    "Tool rentals",
    "Orchard labelling",
    "Bicycle lanes",
    "Festival safety",
    "Bridge tolls",
    "Cellar hygiene",
    "Courier handling",
    "Clock accuracy",
    "Beehive keeping",
    "Lantern hire",
    "Ticket refunds",
    "Footpath upkeep",
]

CONCLUSIONS = [
    "liable",
    "not liable",
    "partially liable",
    "no violation",
    "violation found",
    "claim dismissed",
    "claim upheld",
]

SUMMARIES = [
    "The provisions cited apply to the facts as described.",
    "The cited rules were in force when the events took place.",
    "Both parties acted within the limits set by the norms below.",
    "The outcome follows directly from the cited provisions.",
    "The reasoning relies on the norms listed in the citations.",
]

FIRST_NAMES = ["anna", "jan", "marta", "piotr", "ewa", "tomasz", "zofia", "adam", "irena", "karol"]
LAST_NAMES = ["nowak", "lis", "mazur", "wrona", "kaczor", "sowa", "baran", "gil", "krol", "bury"]

DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

ACTIVE = [f"ACT-{n:03d}" for n in range(1, 25)]
REPEALED = [f"ACT-{n:03d}" for n in range(25, 33)]
WINDOWED = [f"ACT-{n:03d}" for n in range(33, 41)]


def build_registry() -> list[dict[str, str]]:
    """Forty fictional norms: 24 in force, 8 repealed, 8 with short windows."""
    records: list[dict[str, str]] = []
    for n in range(1, 41):
        end: date | None
        if n <= 24:
            start = date(2005, 1, 1) + timedelta(days=n * 173)
            end = date(2027, 1, 1) + timedelta(days=n * 41) if n % 3 == 0 else None
        elif n <= 32:
            start = date(1998, 1, 1) + timedelta(days=n * 211)
            end = date(2014, 12, 31) + timedelta(days=(n - 24) * 257)
        else:
            start = date(2023, 1, 1) + timedelta(days=(n - 32) * 37)
            end = start + timedelta(days=300 + (n - 32) * 11)
        record = {
            "id": f"ACT-{n:03d}",
            "title": f"{TOPICS[n - 1]} Act (fictional)",
            "effective_from": start.isoformat(),
        }
        if end is not None:
            assert end > start, record
            record["effective_to"] = end.isoformat()
        records.append(record)
    return records


def _window(norm_id: str, records: list[dict[str, str]]) -> tuple[date, date]:
    record = next(r for r in records if r["id"] == norm_id)
    return date.fromisoformat(record["effective_from"]), date.fromisoformat(record["effective_to"])


# --- building blocks -------------------------------------------------------------------


def _answer(i: int, citations: list[str], summary: str | None = None) -> dict[str, Any]:
    return {
        "conclusion": CONCLUSIONS[i % len(CONCLUSIONS)],
        "confidence": round(0.55 + (i * 7 % 40) / 100, 2),
        "citations": list(citations),
        "summary": SUMMARIES[i % len(SUMMARIES)] if summary is None else summary,
    }


def _pick(i: int, count: int) -> list[str]:
    """Distinct norms in force on ``AS_OF``."""
    return [ACTIVE[(i * 5 + j * 7) % len(ACTIVE)] for j in range(count)]


def _shifted(confidence: float, by: float) -> float:
    return round(confidence + by if confidence + by <= 1 else confidence - by, 2)


def _variant(output: dict[str, Any]) -> dict[str, Any]:
    """An independent-looking second answer that still agrees with ``output``."""
    second = dict(output)
    second["conclusion"] = f"  {str(output['conclusion']).upper()} "
    second["confidence"] = _shifted(float(output["confidence"]), 0.04)
    second["citations"] = list(reversed(output["citations"]))
    return second


def _opposite(output: dict[str, Any]) -> dict[str, Any]:
    """A second answer that reaches a different conclusion."""
    others = [c for c in CONCLUSIONS if c != output["conclusion"]]
    second = dict(output)
    second["conclusion"] = others[len(output["citations"]) % len(others)]
    return second


def _second_for(i: int, output: dict[str, Any]) -> dict[str, Any]:
    """Mostly agreeing, but every fourth case the other model disagrees."""
    return _opposite(output) if i % 4 == 3 else _variant(output)


class _Cases:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(
        self,
        category: str,
        expected: str,
        output: Any,
        second_opinion: Any,
        *,
        as_of: date = AS_OF,
        note: str = "",
    ) -> None:
        self.items.append(
            {
                "id": f"c{len(self.items) + 1:03d}",
                "category": category,
                "expected": expected,
                "as_of": as_of.isoformat(),
                "output": output,
                "second_opinion": second_opinion,
                "note": note,
            }
        )


# --- identifiers with valid checksums ----------------------------------------------------


def _pesel_check_digit(body: str) -> int:
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(d) * w for d, w in zip(body, weights, strict=True)) % 10) % 10


def _pesel_body(i: int) -> str:
    year, month, day = 1950 + (i * 7) % 50, 1 + (i * 5) % 12, 1 + (i * 11) % 28
    return f"{year % 100:02d}{month:02d}{day:02d}{(i * 37) % 1000:03d}{(i * 3) % 10}"


def _pesel(i: int) -> str:
    body = _pesel_body(i)
    return body + str(_pesel_check_digit(body))


def _not_a_pesel(i: int) -> str:
    """Eleven digits whose last digit breaks the PESEL checksum."""
    body = _pesel_body(i)
    return body + str((_pesel_check_digit(body) + 1) % 10)


def _iban(i: int) -> str:
    bban = f"{10901014 + i:08d}{(i * 7919) % 10**16:016d}"
    return f"PL{98 - int(bban + '252100') % 97:02d}{bban}"


def _groups(text: str, size: int = 4, sep: str = " ") -> str:
    return sep.join(text[k : k + size] for k in range(0, len(text), size))


def _phone_digits(i: int) -> tuple[str, str, str]:
    return f"{500 + i % 99:03d}", f"{100 + (i * 13) % 900:03d}", f"{100 + (i * 29) % 900:03d}"


def _email(i: int, domain_index: int = 0) -> str:
    domain = ("example.com", "example.org", "example.net")[domain_index % 3]
    return f"{FIRST_NAMES[i % 10]}.{LAST_NAMES[(i * 3) % 10]}{i}@{domain}"


# --- categories ---------------------------------------------------------------------------


def _clean(cases: _Cases) -> None:
    """30 well-formed answers; the last six are traps for naive PII scanners."""
    for i in range(24):
        output = _answer(i, _pick(i, 1 + i % 3))
        second = _variant(output)
        if i % 5 == 0:
            second["citations"] = [*second["citations"], _pick(i + 1, 1)[0]]
        cases.add("clean", "publish", output, second, note="valid, in force, no PII, models agree")
    for i in range(4):
        text = f"Registry reference {482915307 + i * 1111}."
        output = _answer(30 + i, _pick(30 + i, 1), summary=text)
        cases.add(
            "clean",
            "publish",
            output,
            _variant(output),
            note="clean text with a nine-digit reference that looks like a phone number",
        )
    for i in range(2):
        text = f"Docket number {_not_a_pesel(40 + i)}."
        output = _answer(40 + i, _pick(40 + i, 1), summary=text)
        cases.add(
            "clean",
            "publish",
            output,
            _variant(output),
            note="clean text with an eleven-digit number that fails the PESEL checksum",
        )


def _repealed(cases: _Cases) -> None:
    for i in range(20):
        cited = [REPEALED[i % 8]] if i % 2 == 0 else [_pick(i, 1)[0], REPEALED[i % 8]]
        output = _answer(i, cited)
        cases.add(
            "repealed_norm",
            "reject",
            output,
            _second_for(i, output),
            note="cites a norm repealed before the as-of date",
        )


def _unknown(cases: _Cases) -> None:
    for i in range(20):
        fake = (
            f"ACT-{41 + i:03d}",
            f"DIR-{2010 + i}-{i + 3:02d}",
            f"REG-{500 + i}",
            f"ACT-{900 + i}",
        )[i % 4]
        cited = [fake] if i % 2 == 0 else [_pick(i, 1)[0], fake]
        output = _answer(i, cited)
        cases.add(
            "unknown_norm",
            "reject",
            output,
            _second_for(i, output),
            note="cites an id that is not in the registry",
        )


def _typos(cases: _Cases, records: list[dict[str, str]]) -> None:
    known = {r["id"] for r in records}
    mutations: tuple[tuple[str, Callable[[str], str]], ...] = (
        ("letter O instead of zero", lambda s: s.replace("0", "O", 1)),
        ("last digit dropped", lambda s: s[:-1]),
        ("extra digit appended", lambda s: s + "0"),
        ("lower case", lambda s: s.lower()),
        ("underscore instead of hyphen", lambda s: s.replace("-", "_")),
        ("transposed letters", lambda s: "ATC" + s[3:]),
        ("trailing dot", lambda s: s + "."),
    )
    for i in range(14):
        label, mutate = mutations[i % len(mutations)]
        target = ACTIVE[(i * 5 + 2) % len(ACTIVE)]
        typo = mutate(target)
        assert typo not in known, typo
        output = _answer(i, [typo] if i % 2 == 0 else [_pick(i, 1)[0], typo])
        cases.add(
            "typo_id",
            "reject",
            output,
            _second_for(i, output),
            note=f"typo of {target}: {label}",
        )
    for i, (target, typo) in enumerate(
        [
            ("ACT-010", "ACT-001"),
            ("ACT-012", "ACT-021"),
            ("ACT-020", "ACT-002"),
            ("ACT-021", "ACT-012"),
            ("ACT-001", "ACT-010"),
            ("ACT-002", "ACT-020"),
        ]
    ):
        assert typo in known
        output = _answer(i, [typo])
        cases.add(
            "typo_id",
            "review",
            output,
            _variant(output),
            note=f"typo of {target} that lands on another real norm in force",
        )


def _boundaries(cases: _Cases, records: list[dict[str, str]]) -> None:
    one_day = timedelta(days=1)
    for i, norm_id in enumerate(WINDOWED[:6]):
        start, end = _window(norm_id, records)
        probes = (
            ("publish", start, "first day of the window (inclusive)"),
            ("publish", end, "last day of the window (inclusive)"),
            ("reject", start - one_day, "day before the norm took effect"),
            ("reject", end + one_day, "day after the norm ended"),
        )
        for expected, as_of, label in probes:
            output = _answer(i, [norm_id])
            cases.add(
                "date_boundary",
                expected,
                output,
                _variant(output),
                as_of=as_of,
                note=f"{norm_id}: {label}",
            )


def _pii_explicit(cases: _Cases) -> None:
    intros = (
        "The applicant can be reached at",
        "Documents should be sent to",
        "Identification given in the file:",
    )
    for i in range(7):
        a, b, c = _phone_digits(i)
        values = {
            "e-mail": _email(i, i),
            "PESEL": _pesel(i),
            "IBAN": _iban(i) if i % 2 == 0 else _groups(_iban(i)),
            "phone": (f"+48 {a} {b} {c}", f"{a}-{b}-{c}", f"{a}{b}{c}", f"+48{a}{b}{c}")[i % 4],
        }
        for kind, value in values.items():
            output = _answer(i, _pick(i, 1 + i % 2), summary=f"{intros[i % 3]} {value}.")
            cases.add(
                "pii_explicit",
                "review",
                output,
                _variant(output),
                note=f"plain {kind} in the summary",
            )


def _pii_masked(cases: _Cases) -> None:
    for i in range(4):
        a, b, c = _phone_digits(i)
        pesel, iban = _pesel(i), _iban(i)
        local = f"{FIRST_NAMES[i]}.{LAST_NAMES[i]}"
        masked = {
            "e-mail": (
                f"{FIRST_NAMES[i]} [at] example dot com",
                f"{local}(at)example(dot)org",
                f"{FIRST_NAMES[i]} at example dot net",
                f"{local} AT example DOT com",
            )[i],
            "PESEL": (
                f"{pesel[:6]} {pesel[6:]}",
                f"{pesel[:2]} {pesel[2:4]} {pesel[4:6]} {pesel[6:]}",
                f"{pesel[:6]}-{pesel[6:]}",
                f"{pesel[:4]} {pesel[4:6]} {pesel[6:]}",
            )[i],
            "IBAN": (
                _groups(iban).lower(),
                _groups(iban, sep="-"),
                f"{iban[:2]} {iban[2:4]} {_groups(iban[4:])}",
                f"{iban[2:4]} {_groups(iban[4:])}",
            )[i],
            "phone": (
                f"{a}.{b}.{c}",
                f"({a}) {b} {c}",
                " ".join(DIGIT_WORDS[int(d)] for d in a + b + c),
                f"{a.replace('0', 'O')} {b.replace('0', 'O')} {c.replace('0', 'O')}",
            )[i],
        }
        for kind, value in masked.items():
            output = _answer(i, _pick(i, 1), summary=f"Contact detail on file: {value}.")
            cases.add(
                "pii_masked",
                "review",
                output,
                _variant(output),
                note=f"{kind} written so that a pattern scanner is expected to miss it",
            )


def _second_opinion(cases: _Cases) -> None:
    for i in range(8):
        output = _answer(i, _pick(i, 3 if i % 8 == 7 else 2))
        second = _variant(output)
        if i % 8 == 1:
            second["citations"] = [*output["citations"], _pick(i + 1, 1)[0]]
        if i % 8 == 2:
            second["confidence"] = _shifted(float(output["confidence"]), 0.25)
        if i % 8 == 7:
            second["citations"] = output["citations"][:2]
        cases.add(
            "second_opinion", "publish", output, second, note="second model agrees (close enough)"
        )
    for i in range(6):
        output = _answer(i + 10, _pick(i + 10, 2))
        cases.add("second_opinion", "review", output, _opposite(output), note="conclusions differ")
    for i in range(3):
        output = _answer(i + 20, _pick(i + 20, 2))
        second = _variant(output)
        second["citations"] = _pick(i + 40, 2)
        cases.add(
            "second_opinion", "review", output, second, note="same conclusion, no shared citation"
        )
    for i in range(3):
        output = _answer(i + 30, _pick(i + 30, 3))
        second = _variant(output)
        second["citations"] = [output["citations"][0], *_pick(i + 50, 3)]
        cases.add(
            "second_opinion",
            "review",
            output,
            second,
            note="same conclusion, low citation overlap",
        )
    for i in range(2):
        output = _answer(i + 40, _pick(i + 40, 2))
        second = _variant(output)
        output["confidence"], second["confidence"] = 0.9, 0.4
        cases.add(
            "second_opinion",
            "review",
            output,
            second,
            note="same conclusion, confidence far apart",
        )
    for i in range(2):
        output = _answer(i + 50, _pick(i + 50, 2))
        cases.add("second_opinion", "review", output, None, note="no second opinion available")


def _schema_errors(cases: _Cases) -> None:
    def broken(i: int, **changes: Any) -> dict[str, Any]:
        output = _answer(i, _pick(i, 2))
        for key, value in changes.items():
            if value is _MISSING:
                del output[key]
            else:
                output[key] = value
        return output

    variants: list[tuple[str, Any]] = [
        ("missing conclusion", broken(0, conclusion=_MISSING)),
        ("missing conclusion", broken(1, conclusion=_MISSING)),
        ("missing confidence", broken(2, confidence=_MISSING)),
        ("missing confidence", broken(3, confidence=_MISSING)),
        ("missing citations", broken(4, citations=_MISSING)),
        ("missing citations", broken(5, citations=_MISSING)),
        ("confidence as text", broken(6, confidence="0.8")),
        ("confidence as text", broken(7, confidence="high")),
        ("confidence above one", broken(8, confidence=1.7)),
        ("confidence as percent", broken(9, confidence=85)),
        ("negative confidence", broken(10, confidence=-0.2)),
        ("boolean confidence", broken(11, confidence=True)),
        ("empty citations", broken(12, citations=[])),
        ("empty citations", broken(13, citations=[])),
        ("citations as text", broken(14, citations="ACT-001")),
        ("citations as text", broken(15, citations="ACT-002, ACT-003")),
        ("citation is a number", broken(16, citations=["ACT-001", 7])),
        ("citation is null", broken(17, citations=[None, "ACT-002"])),
        ("empty conclusion", broken(18, conclusion="")),
        ("conclusion is a number", broken(19, conclusion=42)),
        ("null conclusion", broken(20, conclusion=None)),
        ("null confidence", broken(21, confidence=None)),
        ("output is a list", [broken(22)]),
        ("output is an unparsed string", json.dumps(broken(23))),
    ]
    for i, (label, output) in enumerate(variants):
        if isinstance(output, dict) and i % 2 == 1:
            second: Any = _answer(i, _pick(i, 2))
        else:
            second = output
        cases.add("schema_error", "reject", output, second, note=label)


_MISSING = object()


def build_cases(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    cases = _Cases()
    _clean(cases)
    _repealed(cases)
    _unknown(cases)
    _typos(cases, records)
    _boundaries(cases, records)
    _pii_explicit(cases)
    _pii_masked(cases)
    _second_opinion(cases)
    _schema_errors(cases)
    return cases.items


def render_registry(records: list[dict[str, str]]) -> str:
    return json.dumps(records, indent=2) + "\n"


def render_cases(cases: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(case, sort_keys=False) + "\n" for case in cases)


def main() -> None:
    records = build_registry()
    cases = build_cases(records)
    # Write bytes so that line endings are LF on every platform.
    REGISTRY_PATH.write_bytes(render_registry(records).encode("utf-8"))
    CASES_PATH.write_bytes(render_cases(cases).encode("utf-8"))
    print(f"wrote {len(records)} norms and {len(cases)} cases")


if __name__ == "__main__":
    main()
