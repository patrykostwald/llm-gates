from __future__ import annotations

import pytest

from llm_gates import Field, Schema

ANSWER = Schema(
    {
        "conclusion": Field(str, choices=("yes", "no")),
        "confidence": Field(float, minimum=0, maximum=1),
        "citations": Field(list, items=Field(str, min_length=1), min_items=1),
        "note": Field(str, required=False),
    }
)

VALID = {"conclusion": "yes", "confidence": 0.9, "citations": ["a"]}


def paths(data: object, schema: Schema = ANSWER) -> list[str]:
    return [error.path for error in schema.validate(data).errors]


def test_valid_output_passes() -> None:
    result = ANSWER.validate(VALID)
    assert result.ok
    assert result.errors == ()


def test_optional_field_may_be_absent_or_present() -> None:
    assert ANSWER.validate({**VALID, "note": "x"}).ok


def test_missing_required_field_reports_path() -> None:
    assert paths({"conclusion": "yes", "confidence": 0.5}) == ["$.citations"]


def test_root_must_be_an_object() -> None:
    result = ANSWER.validate(["not", "an", "object"])
    assert [str(e) for e in result.errors] == ["$: expected object, got array"]


@pytest.mark.parametrize(
    ("value", "described"),
    [
        (None, "null"),
        (True, "boolean"),
        (3, "integer"),
        (1.5, "number"),
        ("s", "string"),
        ({"a": 1}, "object"),
        (object(), "object"),
    ],
)
def test_wrong_type_names_the_actual_type(value: object, described: str) -> None:
    errors = Schema({"x": Field(list)}).validate({"x": value}).errors
    assert [e.message for e in errors] == [f"expected array, got {described}"]


def test_bool_is_not_an_integer_or_number() -> None:
    schema = Schema({"i": Field(int), "f": Field(float)})
    assert paths({"i": True, "f": False}, schema) == ["$.i", "$.f"]


def test_integer_is_accepted_as_float_but_not_the_reverse() -> None:
    schema = Schema({"i": Field(int), "f": Field(float)})
    assert schema.validate({"i": 1, "f": 1}).ok
    assert paths({"i": 1.0, "f": 1.0}, schema) == ["$.i"]


def test_bool_field_accepts_only_booleans() -> None:
    schema = Schema({"b": Field(bool)})
    assert schema.validate({"b": True}).ok
    assert not schema.validate({"b": 1}).ok


def test_choices_reject_other_values() -> None:
    errors = ANSWER.validate({**VALID, "conclusion": "maybe"}).errors
    assert [str(e) for e in errors] == ["$.conclusion: must be one of: 'yes', 'no'"]


def test_numeric_bounds_are_inclusive() -> None:
    assert ANSWER.validate({**VALID, "confidence": 0}).ok
    assert ANSWER.validate({**VALID, "confidence": 1}).ok
    assert paths({**VALID, "confidence": -0.01}) == ["$.confidence"]
    assert paths({**VALID, "confidence": 1.01}) == ["$.confidence"]


def test_empty_list_violates_min_items() -> None:
    assert paths({**VALID, "citations": []}) == ["$.citations"]


def test_list_items_are_checked_with_index_in_path() -> None:
    assert paths({**VALID, "citations": ["ok", 5, ""]}) == ["$.citations[1]", "$.citations[2]"]


def test_list_without_items_rule_accepts_anything() -> None:
    assert Schema({"x": Field(list)}).validate({"x": [1, "a", None]}).ok


def test_nested_object_paths() -> None:
    schema = Schema({"author": Field(Schema({"name": Field(str)}))})
    assert paths({"author": {"name": 3}}, schema) == ["$.author.name"]
    assert paths({"author": "bob"}, schema) == ["$.author"]
    assert paths({"author": {}}, schema) == ["$.author.name"]


def test_list_of_objects() -> None:
    schema = Schema({"rows": Field(list, items=Field(Schema({"id": Field(int)})))})
    assert paths({"rows": [{"id": 1}, {"id": "x"}, 7]}, schema) == ["$.rows[1].id", "$.rows[2]"]


def test_extra_fields_allowed_by_default_and_forbidden_on_request() -> None:
    assert ANSWER.validate({**VALID, "extra": 1}).ok
    strict = Schema({"a": Field(int)}, allow_extra=False)
    assert paths({"a": 1, "b": 2}, strict) == ["$.b"]


def test_all_errors_are_collected() -> None:
    assert len(paths({"conclusion": 1, "confidence": "x"})) == 3


def test_error_string_format() -> None:
    error = Schema({"a": Field(int)}).validate({}).errors[0]
    assert str(error) == "$.a: required field is missing"


def test_unsupported_field_type_is_rejected_at_definition() -> None:
    with pytest.raises(TypeError, match="unsupported field type"):
        Field(dict)


def test_items_only_allowed_on_lists() -> None:
    with pytest.raises(TypeError, match="only allowed for list"):
        Field(str, items=Field(str))
