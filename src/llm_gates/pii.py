"""A small scanner for personal data in model output.

Detects e-mail addresses, phone numbers, IBANs (mod-97 verified), Polish
PESEL numbers (checksum verified) and street addresses written with ``ul.``.

Some common ways of hiding a value from a naive scanner are handled:

* **Masked e-mail addresses**: ``jan [at] example dot com``,
  ``jan(at)example.com``, ``jan.lis(at)example(dot)org`` and the bare-word form
  ``jan AT example DOT com``. Brackets may be ``[]``, ``()``, ``{}`` or ``<>``.
  The bare ``at`` form needs ``dot`` written out, otherwise ordinary prose such
  as "look at example.com" would match.
* **PESEL numbers split with spaces or a hyphen between any digits**
  (``440514 01359``, ``44 05 14 01 359``, ``440514-01359``).
* **IBANs in any case, with spaces or hyphens between any characters**
  (``pl61 1090 ...``, ``PL61-1090-...``, ``PL 61 1090 ...``), and Polish
  26-digit account numbers (NRB) without the ``PL`` prefix.

Limitations
-----------
This is a tripwire, not a privacy guarantee.

* **No match does not mean no personal data.** Names, free-text descriptions,
  dates of birth, other countries' ID numbers (except IBANs) and addresses
  without ``ul.`` are not detected.
* **Obfuscation is an arms race.** Spelled-out digits ("five zero zero ..."),
  letters in place of digits (``5OO``), dotted or parenthesised phone numbers
  (``500.100.100``, ``(500) 100 100``), e-mail addresses with other words in
  place of ``at`` and ``dot`` and anything that needs context to read are not
  detected.
* Phone detection is deliberately loose (nine digits, optional ``+CC`` prefix)
  and will flag some nine-digit identifiers. Expect false positives.
* The bare-word e-mail form can flag prose such as "meet at harbour dot com".
  Spaced PESEL numbers are checked for a plausible date as well as the
  checksum, which still lets a few random 11-digit runs through.
* IBANs are recognised only with a known country prefix and the exact length
  for that country (or as a Polish NRB), and must pass the mod-97 check.
* Only strings are scanned; numbers stored as JSON numbers are ignored.

Use it to route output to a human, never to certify output as anonymous.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum


class PiiKind(str, Enum):
    """Category of detected personal data."""

    EMAIL = "email"
    IBAN = "iban"
    PESEL = "pesel"
    PHONE = "phone"
    ADDRESS = "address"


@dataclass(frozen=True, slots=True)
class PiiMatch:
    """One hit. ``path`` locates the string inside the scanned value."""

    kind: PiiKind
    text: str
    path: str
    start: int
    end: int


Span = tuple[int, int]
Finder = Callable[[str], Iterator[Span]]

# The lookbehind starts a match only at the beginning of a token, which keeps the
# scan linear on long runs of address characters.
_LOCAL_PART = r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+"
_EMAIL = re.compile(_LOCAL_PART + r"@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_AT_BRACKETED = r"\s*[\[({<]\s*(?:at|@)\s*[\])}>]\s*"
_DOT_WORD = r"(?:\s+dot\s+|\s*[\[({<]\s*dot\s*[\])}>]\s*)"
_DOT_ANY = rf"(?:\.|{_DOT_WORD})"
_LABEL = r"[A-Za-z0-9-]+"
_TLD = r"[A-Za-z]{2,}"
_MASKED_EMAIL_BRACKETED = re.compile(
    rf"{_LOCAL_PART}{_AT_BRACKETED}{_LABEL}(?:{_DOT_ANY}{_LABEL})*{_DOT_ANY}{_TLD}", re.IGNORECASE
)
_MASKED_EMAIL_WORDS = re.compile(
    rf"{_LOCAL_PART}\s+at\s+{_LABEL}(?:{_DOT_WORD}{_LABEL})*{_DOT_WORD}{_TLD}", re.IGNORECASE
)

# A gap inside a number: spaces, or one hyphen with spaces around it.
_GAP = r"(?:[ \u00a0]+|[ \u00a0]*-[ \u00a0]*)"
_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
_PESEL_SPACED = re.compile(rf"(?<![\d+])(?=(\d(?:{_GAP}?\d){{10}})(?!\d))")
_PHONE = re.compile(r"(?<![\d+])(?:\+\d{1,3}[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3}(?!\d)")
_ADDRESS = re.compile(r"\b(?i:ul)\.\s+[^\W\d_][\w .'-]{1,60}?\s\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?")

_IBAN_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}[ \u00a0-]?\d{2}")
_NRB_START = re.compile(r"(?<![A-Za-z0-9])\d{2}")
_GAP_CHARACTERS = " \u00a0-"
_NRB_LENGTH = 26

# IBAN length per country (SWIFT registry). A candidate must have exactly this length.
_IBAN_TABLE = (
    "AD=24 AE=23 AL=28 AT=20 AZ=28 BA=20 BE=16 BG=22 BH=22 BR=29 BY=28 CH=21 CR=22 "
    "CY=28 CZ=24 DE=22 DK=18 DO=28 EE=20 EG=29 ES=24 FI=18 FO=18 FR=27 GB=22 GE=22 "
    "GI=23 GL=18 GR=27 GT=28 HR=21 HU=28 IE=22 IL=23 IQ=23 IS=26 IT=27 JO=30 KW=30 "
    "KZ=20 LB=28 LC=32 LI=21 LT=20 LU=20 LV=21 MC=27 MD=24 ME=22 MK=19 MR=27 MT=31 "
    "MU=30 NL=18 NO=15 PK=24 PL=28 PS=29 PT=25 QA=29 RO=24 RS=22 SA=24 SC=31 SE=24 "
    "SI=19 SK=24 SM=27 ST=25 SV=28 TL=23 TN=24 TR=26 UA=29 VA=22 VG=24 XK=20"
)
_IBAN_LENGTHS = {entry[:2]: int(entry[3:]) for entry in _IBAN_TABLE.split()}

_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def _pesel_valid(digits: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits, _PESEL_WEIGHTS, strict=False))
    return (10 - total % 10) % 10 == int(digits[10])


def _pesel_date_plausible(digits: str) -> bool:
    """Month (offset by century) from 1 to 12 and day from 1 to 31."""
    return 1 <= int(digits[2:4]) % 20 <= 12 and 1 <= int(digits[4:6]) <= 31


def _iban_valid(compact: str) -> bool:
    """Known country, exact length for it, and mod-97 equal to one."""
    compact = compact.upper()
    if _IBAN_LENGTHS.get(compact[:2]) != len(compact):
        return False
    rearranged = compact[4:] + compact[:4]
    number = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(number) % 97 == 1


def _regex_finder(
    pattern: re.Pattern[str], validate: Callable[[str], bool] | None = None
) -> Finder:
    def find(text: str) -> Iterator[Span]:
        for found in pattern.finditer(text):
            if validate is None or validate(found.group()):
                yield found.start(), found.end()

    return find


def _runs(
    text: str, start: int, accepts: Callable[[str], bool], limit: int
) -> Iterator[tuple[int, str]]:
    """Walk from ``start`` over characters that ``accepts``, skipping any number of spaces and
    hyphens between them, and yield ``(end, compact text)`` at every token boundary."""
    pos = start
    taken: list[str] = []
    while pos < len(text) and len(taken) < limit:
        char = text[pos]
        if accepts(char):
            taken.append(char)
            pos += 1
            if pos == len(text) or not accepts(text[pos]):
                yield pos, "".join(taken)
        elif char in _GAP_CHARACTERS:
            pos += 1
        else:
            break


def _is_ascii_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _is_ascii_digit(char: str) -> bool:
    return char.isascii() and char.isdigit()


def _prefixed_iban_spans(text: str) -> Iterator[Span]:
    for found in _IBAN_START.finditer(text):
        longest = None
        for end, compact in _runs(text, found.start(), _is_ascii_alnum, 34):
            if _iban_valid(compact):
                longest = end
        if longest is not None:
            yield found.start(), longest


def _nrb_spans(text: str) -> Iterator[Span]:
    """Polish account numbers: 26 digits, the IBAN without ``PL``."""
    for found in _NRB_START.finditer(text):
        for end, compact in _runs(text, found.start(), _is_ascii_digit, _NRB_LENGTH):
            if len(compact) == _NRB_LENGTH and _iban_valid("PL" + compact):
                yield found.start(), end


def _spaced_pesel_spans(text: str) -> Iterator[Span]:
    for found in _PESEL_SPACED.finditer(text):
        digits = re.sub(r"\D", "", found.group(1))
        if _pesel_valid(digits) and _pesel_date_plausible(digits):
            yield found.start(1), found.end(1)


_DETECTORS: tuple[tuple[PiiKind, Finder], ...] = (
    (PiiKind.EMAIL, _regex_finder(_EMAIL)),
    (PiiKind.EMAIL, _regex_finder(_MASKED_EMAIL_BRACKETED)),
    (PiiKind.EMAIL, _regex_finder(_MASKED_EMAIL_WORDS)),
    (PiiKind.IBAN, _prefixed_iban_spans),
    (PiiKind.IBAN, _nrb_spans),
    (PiiKind.PESEL, _regex_finder(_PESEL, _pesel_valid)),
    (PiiKind.PESEL, _spaced_pesel_spans),
    (PiiKind.PHONE, _regex_finder(_PHONE)),
    (PiiKind.ADDRESS, _regex_finder(_ADDRESS)),
)


def _scan_string(text: str, path: str) -> list[PiiMatch]:
    hits: list[PiiMatch] = []
    for kind, find in _DETECTORS:
        for start, end in find(text):
            if any(start < h.end and h.start < end for h in hits):
                continue
            hits.append(PiiMatch(kind, text[start:end], path, start, end))
    return sorted(hits, key=lambda hit: hit.start)


def find_pii(value: object, path: str = "$") -> list[PiiMatch]:
    """Scan a string, or every string inside nested lists and dicts.

    Dict keys are not scanned. Earlier detectors win when two matches overlap
    (e-mail, IBAN, PESEL, phone, address, in that order).
    """
    if isinstance(value, str):
        return _scan_string(value, path)
    if isinstance(value, Mapping):
        return [hit for key, item in value.items() for hit in find_pii(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [hit for i, item in enumerate(value) for hit in find_pii(item, f"{path}[{i}]")]
    return []
