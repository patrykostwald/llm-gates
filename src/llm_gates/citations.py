"""Check that every norm an output cites exists and is in force.

A :class:`NormRegistry` holds the norms you trust (statutes, regulations,
internal policies, anything with an id and a validity window).
:func:`verify_citations` then checks the ids cited by a model against it.

Validity windows are inclusive on both ends: a norm with
``effective_from=2024-01-01`` and ``effective_to=2024-12-31`` is in force on
both of those days. An empty ``effective_to`` means "still in force".
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

_ID_PATTERN = re.compile(r"\S+")


class RegistryError(ValueError):
    """Raised when registry data is malformed."""


@dataclass(frozen=True, slots=True)
class Norm:
    """A citable norm with an inclusive validity window."""

    id: str
    title: str
    effective_from: date
    effective_to: date | None = None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.id):
            raise RegistryError(f"invalid norm id: {self.id!r}")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise RegistryError(f"norm {self.id!r} ends before it starts")

    def in_force(self, on: date) -> bool:
        """Whether the norm is in force on the given day."""
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


class NormRegistry:
    """A set of norms indexed by id."""

    def __init__(self, norms: Iterable[Norm] = ()) -> None:
        self._norms: dict[str, Norm] = {}
        for norm in norms:
            self.add(norm)

    def add(self, norm: Norm) -> None:
        """Register a norm; ids must be unique."""
        if norm.id in self._norms:
            raise RegistryError(f"duplicate norm id: {norm.id!r}")
        self._norms[norm.id] = norm

    def get(self, norm_id: str) -> Norm | None:
        """Return the norm with this id, or ``None``."""
        return self._norms.get(norm_id)

    def __contains__(self, norm_id: object) -> bool:
        return norm_id in self._norms

    def __len__(self) -> int:
        return len(self._norms)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> NormRegistry:
        """Build a registry from dicts with ``id``, ``title``, ``effective_from``
        and an optional ``effective_to`` (ISO ``YYYY-MM-DD`` dates)."""
        return cls(_norm_from_record(record) for record in records)

    @classmethod
    def from_json(cls, path: str | Path) -> NormRegistry:
        """Load a JSON file containing a list of norm records."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise RegistryError("JSON registry must be a list of objects")
        return cls.from_records(data)

    @classmethod
    def from_csv(cls, path: str | Path) -> NormRegistry:
        """Load a CSV file with the columns ``id,title,effective_from,effective_to``."""
        with Path(path).open(encoding="utf-8", newline="") as handle:
            return cls.from_records(csv.DictReader(handle))


def _norm_from_record(record: Mapping[str, Any]) -> Norm:
    try:
        return Norm(
            id=str(record["id"]).strip(),
            title=str(record["title"]),
            effective_from=_parse_date(record["effective_from"]),
            effective_to=_parse_optional_date(record.get("effective_to")),
        )
    except KeyError as missing:
        raise RegistryError(f"norm record is missing {missing}") from None


def _parse_date(value: object) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise RegistryError(f"invalid date: {value!r} (expected YYYY-MM-DD)") from None


def _parse_optional_date(value: object) -> date | None:
    if value is None or not str(value).strip():
        return None
    return _parse_date(value)


class ProblemKind(str, Enum):
    """Why a citation failed."""

    UNKNOWN = "unknown"
    NOT_IN_FORCE = "not_in_force"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class CitationProblem:
    """One failed citation."""

    citation: object
    kind: ProblemKind
    detail: str

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.detail}"


@dataclass(frozen=True, slots=True)
class CitationReport:
    """Outcome of :func:`verify_citations`."""

    checked: int
    problems: tuple[CitationProblem, ...]

    @property
    def ok(self) -> bool:
        """True when every citation exists and is in force."""
        return not self.problems


def verify_citations(
    output: Mapping[str, Any],
    registry: NormRegistry,
    as_of: date,
    *,
    field: str = "citations",
) -> CitationReport:
    """Check the norm ids listed under ``output[field]`` against ``registry``.

    A missing field counts as zero citations (use a schema to require it). Each
    entry must be a non-blank string without whitespace; entries that are not
    are reported as ``malformed``. Well-formed ids that the registry does not
    know are ``unknown``; known ids outside their validity window on ``as_of``
    are ``not_in_force``.
    """
    raw = output.get(field, [])
    if not isinstance(raw, list):
        problem = CitationProblem(raw, ProblemKind.MALFORMED, f"'{field}' must be a list")
        return CitationReport(checked=0, problems=(problem,))
    problems = [p for entry in raw if (p := _check_one(entry, registry, as_of)) is not None]
    return CitationReport(checked=len(raw), problems=tuple(problems))


def _check_one(entry: object, registry: NormRegistry, as_of: date) -> CitationProblem | None:
    if not isinstance(entry, str) or not _ID_PATTERN.fullmatch(entry):
        return CitationProblem(entry, ProblemKind.MALFORMED, f"not a valid norm id: {entry!r}")
    norm = registry.get(entry)
    if norm is None:
        return CitationProblem(entry, ProblemKind.UNKNOWN, f"{entry} is not in the registry")
    if not norm.in_force(as_of):
        return CitationProblem(
            entry, ProblemKind.NOT_IN_FORCE, f"{entry} is not in force on {as_of.isoformat()}"
        )
    return None
