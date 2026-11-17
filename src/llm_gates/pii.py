"""A small scanner for personal data in model output.

Detects e-mail addresses, phone numbers, IBANs (mod-97 verified), Polish
PESEL numbers (checksum verified) and street addresses written with ``ul.``.

Limitations
-----------
This is a tripwire, not a privacy guarantee.

* **No match does not mean no personal data.** Names, free-text descriptions,
  dates of birth, other countries' ID numbers, addresses without ``ul.`` and
  anything obfuscated ("jan at example dot com") are not detected.
* Phone detection is deliberately loose (nine digits, optional ``+CC`` prefix)
  and will flag some nine-digit identifiers. Expect false positives.
* IBANs are only recognised with their country prefix.
* Only strings are scanned; numbers stored as JSON numbers are ignored.

Use it to route output to a human, never to certify output as anonymous.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
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


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_IBAN = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"
)
_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
_PHONE = re.compile(r"(?<![\d+])(?:\+\d{1,3}[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3}(?!\d)")
_ADDRESS = re.compile(r"\b(?i:ul)\.\s+[^\W\d_][\w .'-]{1,60}?\s\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?")

_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def _pesel_valid(digits: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits, _PESEL_WEIGHTS, strict=False))
    return (10 - total % 10) % 10 == int(digits[10])


def _iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    number = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(number) % 97 == 1


def _scan_string(text: str, path: str) -> list[PiiMatch]:
    hits: list[PiiMatch] = []
    detectors = (
        (PiiKind.EMAIL, _EMAIL, None),
        (PiiKind.IBAN, _IBAN, _iban_valid),
        (PiiKind.PESEL, _PESEL, _pesel_valid),
        (PiiKind.PHONE, _PHONE, None),
        (PiiKind.ADDRESS, _ADDRESS, None),
    )
    for kind, pattern, validate in detectors:
        for found in pattern.finditer(text):
            overlaps = any(found.start() < h.end and h.start < found.end() for h in hits)
            if overlaps or (validate is not None and not validate(found.group())):
                continue
            hits.append(PiiMatch(kind, found.group(), path, found.start(), found.end()))
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
