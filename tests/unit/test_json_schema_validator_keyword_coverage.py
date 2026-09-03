"""#1509: the stdlib validator must not pass by declining to look.

``agent-runtime/scripts/ci/json_schema_validate.py`` is the repo's only JSON
Schema validator — the CI directory is stdlib-only, so ``jsonschema`` is not an
option and never will be. Its founding defect is that it **silently ignored
every keyword it did not implement**. A schema author writes a constraint, the
validator returns ``[]``, and the constraint is enforced nowhere. Nothing in the
schema file or the validator's output distinguishes "checked and satisfied" from
"never looked at".

Three constraint forms were confirmed live in the published schemas and enforced
nowhere:

* ``maximum`` — 11 occurrences across 4 schemas, e.g. every ``*_threshold`` in
  ``harness-config`` is documented as a 0..1 ratio and a 900 was accepted.
* ``format: "date"`` — ``review-artifact.schema.json``; only ``date-time`` was
  implemented, so the other format string fell through the same silent hole.
* ``additionalProperties: <subschema>`` — 7 occurrences; only the ``false`` form
  was implemented, so the *value* constraint on an open map was a no-op.

A peer hit the same class of defect from the other side on #1441: they added
``oneOf`` support precisely because the two-shape ``tokenUsage`` contract would
otherwise have been published and unenforced.

So implementing those three is only half a fix — the next unimplemented keyword
would be just as invisible. The other half is a **closed allowlist**: a keyword
the validator does not know is now reported as an error rather than skipped.
``test_the_published_schemas_use_no_keyword_the_validator_cannot_enforce`` is the
durable guard; it is the test that would have caught ``maximum`` on the day it
was written.

Every test here plants a lie and asserts it is caught.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
SCHEMA_DIR = REPO_ROOT / "agent-runtime" / "docs" / "schemas"


def _load_seam():
    """Import the stdlib validator.

    Inside a function on purpose: hoisting the ``sys.path`` insert above the
    module-level imports needs a ``# noqa: E402``, and the repo's debt ratchet
    counts suppression identities rather than a total.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import json_schema_validate

    return json_schema_validate


json_schema_validate = _load_seam()
validate_json_schema = json_schema_validate.validate_json_schema

ISSUE = 1509


# --------------------------------------------------------------------------
# Half 1 — keywords that were used in published schemas and enforced nowhere
# --------------------------------------------------------------------------


def test_a_value_above_maximum_is_rejected() -> None:
    """The lie: a ratio of 900 where the schema says ``maximum: 1``."""
    schema = {"type": "number", "minimum": 0, "maximum": 1}
    errors = validate_json_schema(900, schema)
    assert errors, "a value above `maximum` was accepted — the keyword is a no-op"
    assert "maximum" in errors[0]


def test_a_value_at_maximum_is_accepted() -> None:
    """``maximum`` is inclusive; enforcing it must not over-reject the boundary."""
    assert validate_json_schema(1, {"type": "number", "minimum": 0, "maximum": 1}) == []


def test_maximum_is_enforced_through_the_published_harness_config_schema() -> None:
    """Not a copy in this test — the schema file on disk.

    ``backend_threshold`` is published as a 0..1 ratio. Before this change a 900
    round-tripped clean.
    """
    schema = json.loads((SCHEMA_DIR / "harness-config.schema.json").read_text("utf-8"))
    routing_schema = schema["properties"]["routing"]
    routing = {
        "backend_threshold": 0.5,
        "ui_threshold": 0.5,
        "data_threshold": 0.5,
        "ml_threshold": 0.5,
    }
    assert validate_json_schema(routing, routing_schema) == []

    errors = validate_json_schema({**routing, "backend_threshold": 900}, routing_schema)
    assert errors, "the published 0..1 threshold accepted 900"
    assert "backend_threshold" in errors[0]


def test_a_bad_date_is_rejected_by_the_date_format() -> None:
    """The lie: a date-time string where the schema published ``format: "date"``."""
    schema = {"type": "string", "format": "date"}
    assert validate_json_schema("2026-09-02", schema) == []
    errors = validate_json_schema("not-a-date", schema)
    assert errors, "`format: date` accepted a non-date — the keyword is a no-op"


def test_additional_properties_subschema_constrains_open_map_values() -> None:
    """The lie: a number where the open map's value schema says non-empty string.

    Only the ``additionalProperties: false`` form was implemented, so the
    subschema form — used 7 times in the published schemas — asserted nothing.
    """
    schema = {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "string"}},
    }
    assert validate_json_schema({"backend": ["a"]}, schema) == []
    errors = validate_json_schema({"backend": 7}, schema)
    assert errors, "the open map accepted a value its own value-schema forbids"


# --------------------------------------------------------------------------
# Half 2 — an unknown keyword must be loud, not invisible
# --------------------------------------------------------------------------


def test_an_unknown_keyword_does_not_pass_silently() -> None:
    """The founding defect, planted directly.

    ``maxLength`` is not implemented. Before this change a 10-character string
    validated clean against ``maxLength: 3`` and the author had no way to know.
    """
    errors = validate_json_schema("wildly-too-long", {"type": "string", "maxLength": 3})
    assert errors, "an unimplemented keyword was skipped in silence"
    assert "maxLength" in errors[0]


def test_an_unknown_keyword_is_reported_even_when_the_instance_is_valid() -> None:
    """Silence is the defect, not the rejection. A conforming instance still tells."""
    errors = validate_json_schema("ok", {"type": "string", "uniqueItems": True})
    assert any("uniqueItems" in error for error in errors)


def test_an_unknown_keyword_inside_a_oneof_branch_names_the_keyword() -> None:
    """A branch defect must not disguise itself as "matched 0 branches".

    Unknown-keyword detection is a *schema* defect and runs once over the whole
    schema, so it survives the branch-matching recursion instead of degrading
    into a misleading arity message.
    """
    schema = {"oneOf": [{"type": "string", "maxLength": 3}, {"type": "integer"}]}
    errors = validate_json_schema("value", schema)
    assert any("maxLength" in error for error in errors), errors


def test_annotation_keywords_are_not_reported_as_unknown() -> None:
    """``title``/``description``/``default`` assert nothing *by specification*.

    They are known-and-inert, which is a different thing from unimplemented. If
    this fails the allowlist has become a nuisance rather than a guard.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.test/x.json",
        "title": "Thing",
        "description": "A thing.",
        "default": "x",
        "type": "string",
    }
    assert validate_json_schema("x", schema) == []


def test_the_allowlist_does_not_quietly_absorb_an_unimplemented_assertion() -> None:
    """Guards the guard.

    An author under time pressure can make a red test green by dropping the
    keyword into the inert set. These four *assert* things; parking any of them
    beside ``title`` would recreate the exact defect this issue closes.
    """
    inert = json_schema_validate.ANNOTATION_KEYWORDS
    for keyword in ("maxLength", "maxItems", "exclusiveMinimum", "uniqueItems"):
        assert keyword not in inert, f"{keyword!r} asserts a constraint; it is not an annotation"


# --------------------------------------------------------------------------
# The durable guard — the test that would have caught `maximum` on day one
# --------------------------------------------------------------------------


def _schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.json"))


@pytest.mark.parametrize("schema_path", _schema_files(), ids=lambda p: p.name)
def test_the_published_schemas_use_no_keyword_the_validator_cannot_enforce(
    schema_path: Path,
) -> None:
    """Every keyword an author published must be one the validator acts on.

    This is the standing version of the defect report: it fails the moment
    someone writes a constraint the validator would otherwise ignore, instead of
    publishing it unenforced and waiting for a reader to notice.
    """
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    unknown = json_schema_validate.unknown_keywords(schema)
    assert unknown == [], f"{schema_path.name} uses unenforced keyword(s): {unknown}"
