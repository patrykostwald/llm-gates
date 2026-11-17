"""Minimal structural validation for model output.

A :class:`Schema` describes an object with named :class:`Field` entries. Each
field has a type, may be required, may restrict its values, and (for lists)
may describe its items. Nested objects use a nested :class:`Schema` as the type.

Every problem is reported as a :class:`SchemaError` carrying the path of the
offending value, for example ``$.citations[2]``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_SCALAR_TYPES: tuple[type, ...] = (str, int, float, bool)
_TYPE_NAMES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
}


@dataclass(frozen=True, slots=True)
class SchemaError:
    """One validation problem, tied to a path inside the validated value."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of :meth:`Schema.validate`."""

    errors: tuple[SchemaError, ...]

    @property
    def ok(self) -> bool:
        """True when no errors were found."""
        return not self.errors


@dataclass(frozen=True, slots=True)
class Field:
    """Rules for one value.

    Args:
        kind: ``str``, ``int``, ``float``, ``bool``, ``list`` or a nested
            :class:`Schema`. ``float`` also accepts integers; ``int`` and
            ``float`` never accept booleans.
        required: whether the key must be present in its parent object.
        choices: if non-empty, the value must equal one of these.
        minimum: inclusive lower bound for ``int`` and ``float`` values.
        maximum: inclusive upper bound for ``int`` and ``float`` values.
        min_length: minimum length of a ``str`` value.
        items: rules for every element of a ``list`` value.
        min_items: minimum number of elements of a ``list`` value.
    """

    kind: type | Schema
    required: bool = True
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    min_length: int = 0
    items: Field | None = None
    min_items: int = 0

    def __post_init__(self) -> None:
        valid = self.kind is list or isinstance(self.kind, Schema) or self.kind in _SCALAR_TYPES
        if not valid:
            raise TypeError(f"unsupported field type: {self.kind!r}")
        if self.items is not None and self.kind is not list:
            raise TypeError("'items' is only allowed for list fields")


@dataclass(frozen=True, slots=True)
class Schema:
    """An object schema: named fields plus a policy for unknown keys."""

    fields: Mapping[str, Field]
    allow_extra: bool = True

    def validate(self, data: object) -> ValidationResult:
        """Validate ``data`` and return every problem found (never raises)."""
        errors: list[SchemaError] = []
        self._check_object(data, "$", errors)
        return ValidationResult(tuple(errors))

    def _check_object(self, data: object, path: str, errors: list[SchemaError]) -> None:
        if not isinstance(data, Mapping):
            errors.append(SchemaError(path, f"expected object, got {_describe(data)}"))
            return
        for name, field in self.fields.items():
            if name not in data:
                if field.required:
                    errors.append(SchemaError(f"{path}.{name}", "required field is missing"))
                continue
            _check_value(field, data[name], f"{path}.{name}", errors)
        if not self.allow_extra:
            errors.extend(
                SchemaError(f"{path}.{key}", "unexpected field")
                for key in data
                if key not in self.fields
            )


_JSON_TYPES: tuple[tuple[type | tuple[type, ...], str], ...] = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (Mapping, "object"),
    (Sequence, "array"),
)


def _describe(value: object) -> str:
    """Name the JSON type of ``value`` for error messages."""
    if value is None:
        return "null"
    return next(
        (name for kind, name in _JSON_TYPES if isinstance(value, kind)), type(value).__name__
    )


def _matches(expected: type, value: object) -> bool:
    """Type check that keeps booleans out of numbers and lets ints be floats."""
    if expected is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if expected is float:
        return isinstance(value, int | float)
    if expected is list:
        return isinstance(value, list)
    return isinstance(value, expected)


def _check_value(field: Field, value: object, path: str, errors: list[SchemaError]) -> None:
    if isinstance(field.kind, Schema):
        field.kind._check_object(value, path, errors)
        return
    if not _matches(field.kind, value):
        expected = _TYPE_NAMES[field.kind]
        errors.append(SchemaError(path, f"expected {expected}, got {_describe(value)}"))
        return
    if field.choices and value not in field.choices:
        allowed = ", ".join(repr(choice) for choice in field.choices)
        errors.append(SchemaError(path, f"must be one of: {allowed}"))
    _check_bounds(field, value, path, errors)


def _check_bounds(field: Field, value: object, path: str, errors: list[SchemaError]) -> None:
    if isinstance(value, str) and len(value) < field.min_length:
        errors.append(SchemaError(path, f"must have at least {field.min_length} characters"))
    elif isinstance(value, int | float) and not isinstance(value, bool):
        if field.minimum is not None and value < field.minimum:
            errors.append(SchemaError(path, f"must be >= {field.minimum}"))
        if field.maximum is not None and value > field.maximum:
            errors.append(SchemaError(path, f"must be <= {field.maximum}"))
    elif isinstance(value, list):
        if len(value) < field.min_items:
            errors.append(SchemaError(path, f"must have at least {field.min_items} items"))
        if field.items is not None:
            for index, item in enumerate(value):
                _check_value(field.items, item, f"{path}[{index}]", errors)
