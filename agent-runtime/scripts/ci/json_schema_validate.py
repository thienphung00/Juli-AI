"""Minimal JSON Schema (draft 2020-12 subset) validator — stdlib only.

Stdlib-only is deliberate, not an oversight: this module runs during status-record
generation in CI, where the dependency set is thin. ``jsonschema`` is not in
``./backend[dev] -c backend/constraints.txt``; a peer who imported it passed
locally and died at CI collection. ``tests/unit/test_implementation_artifact_contract.py``
plants that lie as an AST-based guard.

Being a *subset* validator is the interesting risk. Until #1509 this module
silently ignored every keyword it did not implement: an author wrote a
constraint, ``validate_json_schema`` returned ``[]``, and the constraint was
enforced nowhere. Nothing distinguished "checked and satisfied" from "never
looked at" — a check that passes by not looking. Three constraint forms were
live in the published schemas and asserting nothing (``maximum`` in 4 schemas,
``format: "date"``, and ``additionalProperties`` in its subschema form).

The structural fix is the **closed allowlist** below. A keyword this module
cannot enforce is now reported as an error instead of skipped, so the *next*
unimplemented constraint is loud on the day it is written rather than invisible
until a reader happens to notice. Two consequences worth stating:

* Adding a keyword to ``ANNOTATION_KEYWORDS`` is not a way to silence a red
  test. That set is for keywords that assert nothing *by specification*
  (``title``, ``description``, ``default``); putting an assertion there
  recreates exactly the defect this design closes, and a test guards it.
* Unimplemented-but-unused keywords (``maxLength``, ``maxItems``,
  ``uniqueItems``, ``exclusiveMinimum``, ``$ref`` …) are deliberately absent.
  Speculative implementations would be untested code; leaving them out is safe
  *because* the allowlist makes their first real use a failure rather than a
  no-op.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_DATE_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Keywords that assert nothing *by JSON Schema specification*. They are inert
#: on purpose, which is a different thing from unimplemented — hence a separate
#: set from the assertions below, so review can see which claim is being made.
#: Do not park an assertion here to quiet a failure.
ANNOTATION_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
    }
)

#: Keywords this module actually enforces. Every name here has a branch in
#: ``validate_json_schema`` and a test that plants a violating value.
ASSERTION_KEYWORDS = frozenset(
    {
        "type",
        "const",
        "enum",
        "oneOf",
        "minLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "minItems",
        "items",
        "required",
        "properties",
        "additionalProperties",
    }
)

KNOWN_KEYWORDS = ANNOTATION_KEYWORDS | ASSERTION_KEYWORDS

#: ``format`` values with a real check. An unrecognised format string is itself
#: a silent-ignore hole one level down, so it is reported like an unknown
#: keyword rather than skipped.
_FORMAT_CHECKERS: dict[str, re.Pattern[str]] = {
    "date-time": _DATE_TIME_RE,
    "date": _DATE_RE,
}


def unknown_keywords(schema: Any, *, path: str = "$") -> list[str]:
    """Return every construct in ``schema`` this module cannot enforce.

    Reports unknown keywords *and* unsupported forms of known ones (an ``items``
    tuple, a non-boolean/non-object ``additionalProperties``, an unrecognised
    ``format``) — an unimplemented form of a known keyword is the same silent
    hole as an unimplemented keyword.

    This walks the schema, not the instance, so a defect is reported once at the
    top level and survives ``oneOf`` branch matching instead of degrading into a
    misleading "matched 0 branches" message.
    """
    defects: list[str] = []
    if not isinstance(schema, dict):
        return defects

    for keyword, value in schema.items():
        if keyword not in KNOWN_KEYWORDS:
            defects.append(f"{path}: unknown keyword {keyword!r} — the validator cannot enforce it")
            continue

        if keyword == "properties" and isinstance(value, dict):
            for name, sub in value.items():
                defects.extend(unknown_keywords(sub, path=f"{path}.{name}"))
        elif keyword == "oneOf" and isinstance(value, list):
            for index, sub in enumerate(value):
                defects.extend(unknown_keywords(sub, path=f"{path}|oneOf[{index}]"))
        elif keyword == "items":
            if isinstance(value, dict):
                defects.extend(unknown_keywords(value, path=f"{path}[]"))
            else:
                defects.append(f"{path}: unsupported 'items' form {type(value).__name__}")
        elif keyword == "additionalProperties":
            if isinstance(value, dict):
                defects.extend(unknown_keywords(value, path=f"{path}.*"))
            elif not isinstance(value, bool):
                defects.append(
                    f"{path}: unsupported 'additionalProperties' form {type(value).__name__}"
                )
        elif keyword == "format" and value not in _FORMAT_CHECKERS:
            defects.append(f"{path}: unknown format {value!r} — the validator cannot enforce it")

    return defects


def validate_json_schema(
    instance: Any, schema: dict[str, Any], *, path: str = "$", _root: bool = True
) -> list[str]:
    """Return a list of validation error messages (empty when valid).

    A schema using a keyword this module cannot enforce yields an error rather
    than a quiet pass — see the module docstring.
    """
    errors: list[str] = []

    def err(message: str) -> None:
        errors.append(f"{path}: {message}")

    if not isinstance(schema, dict):
        err("schema must be an object")
        return errors

    # Schema defects are reported once, from the entry call. Doing it here
    # rather than inside the recursion keeps an unenforceable keyword inside a
    # ``oneOf`` branch reported as *itself*, instead of silently making that
    # branch fail to match and surfacing as a branch-arity error.
    if _root:
        errors.extend(unknown_keywords(schema, path=path))

    # ``oneOf`` — added for #1441, where ``tokenUsage`` must admit exactly two
    # shapes (a measured reading, or ``{available: false, reason}`` with no
    # ``value`` key) and nothing else.
    branches = schema.get("oneOf")
    if isinstance(branches, list) and branches:
        matched = [
            index
            for index, branch in enumerate(branches)
            if not validate_json_schema(instance, branch, path=path, _root=False)
        ]
        if len(matched) != 1:
            titles = [
                str(b.get("title") or i) for i, b in enumerate(branches) if isinstance(b, dict)
            ]
            err(
                f"matched {len(matched)} of {len(branches)} oneOf branches "
                f"({', '.join(titles)}); exactly one must match"
            )
            return errors

    schema_type = schema.get("type")
    if schema_type is not None:
        if not _type_matches(instance, schema_type):
            err(f"expected type {schema_type!r}, got {type(instance).__name__}")
            return errors

    if "const" in schema and instance != schema["const"]:
        err(f"expected const {schema['const']!r}, got {instance!r}")
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        err(f"value {instance!r} not in enum {schema['enum']!r}")
        return errors

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            err(f"string shorter than minLength {schema['minLength']}")
        if "pattern" in schema and not re.match(str(schema["pattern"]), instance):
            err(f"string does not match pattern {schema['pattern']!r}")
        if "format" in schema:
            errors.extend(_format_errors(instance, str(schema["format"]), path))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            err(f"value {instance} below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            err(f"value {instance} above maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < int(schema["minItems"]):
            err(f"array shorter than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(
                    validate_json_schema(item, item_schema, path=f"{path}[{index}]", _root=False)
                )

    if isinstance(instance, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")

        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties")
        if additional is False:
            allowed = set(properties.keys())
            for key in instance:
                if key not in allowed:
                    errors.append(f"{path}: additional property {key!r} is not allowed")

        for key, value in instance.items():
            if key in properties:
                errors.extend(
                    validate_json_schema(value, properties[key], path=f"{path}.{key}", _root=False)
                )
            elif isinstance(additional, dict):
                # The subschema form constrains the *values* of an open map.
                # Implemented for #1509: previously only the ``false`` form was
                # handled, so these 7 published constraints asserted nothing.
                errors.extend(
                    validate_json_schema(value, additional, path=f"{path}.{key}", _root=False)
                )

    return errors


def _format_errors(instance: str, format_name: str, path: str) -> list[str]:
    """Check a ``format`` value, reporting an unrecognised format as a defect."""
    checker = _FORMAT_CHECKERS.get(format_name)
    if checker is None:
        return [f"{path}: unknown format {format_name!r} — the validator cannot enforce it"]
    if not checker.match(instance):
        return [f"{path}: string is not a valid {format_name}: {instance!r}"]
    if format_name == "date-time":
        try:
            datetime.fromisoformat(instance.replace("Z", "+00:00"))
        except ValueError:
            return [f"{path}: string is not a valid date-time: {instance!r}"]
    elif format_name == "date":
        try:
            datetime.strptime(instance, "%Y-%m-%d")
        except ValueError:
            return [f"{path}: string is not a valid date: {instance!r}"]
    return []


def _type_matches(instance: Any, schema_type: str | list[str]) -> bool:
    types = [schema_type] if isinstance(schema_type, str) else list(schema_type)
    for type_name in types:
        if type_name == "null" and instance is None:
            return True
        if type_name == "boolean" and isinstance(instance, bool):
            return True
        if type_name == "object" and isinstance(instance, dict):
            return True
        if type_name == "array" and isinstance(instance, list):
            return True
        if type_name == "string" and isinstance(instance, str):
            return True
        if type_name == "integer" and isinstance(instance, int) and not isinstance(instance, bool):
            return True
        if (
            type_name == "number"
            and isinstance(instance, (int, float))
            and not isinstance(instance, bool)
        ):
            return True
    return False
