"""Validate implementation artifacts against implementation-artifact.schema.json."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from common import AGENT_RUNTIME_ROOT, load_json
from json_schema_validate import validate_json_schema

SCHEMA_PATH = AGENT_RUNTIME_ROOT / "docs" / "schemas" / "implementation-artifact.schema.json"


@lru_cache(maxsize=1)
def load_implementation_schema() -> dict[str, Any]:
    return load_json(SCHEMA_PATH)


def validate_implementation_artifact(artifact: Any) -> dict[str, Any]:
    """Return ``{valid, errors}`` for a parsed implementation artifact."""
    schema = load_implementation_schema()
    errors = validate_json_schema(artifact, schema)
    return {"valid": not errors, "errors": errors}
