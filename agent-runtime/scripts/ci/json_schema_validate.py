"""Minimal JSON Schema (draft 2020-12 subset) validator — stdlib only."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def validate_json_schema(instance: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Return a list of validation error messages (empty when valid)."""
    errors: list[str] = []

    def err(message: str) -> None:
        errors.append(f"{path}: {message}")

    if not isinstance(schema, dict):
        err("schema must be an object")
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
        if schema.get("format") == "date-time" and not _DATE_TIME_RE.match(instance):
            err(f"string is not a valid date-time: {instance!r}")
            try:
                normalized = instance.replace("Z", "+00:00")
                datetime.fromisoformat(normalized)
            except ValueError:
                if f"string is not a valid date-time: {instance!r}" not in errors[-1:]:
                    err(f"string is not a valid date-time: {instance!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            err(f"value {instance} below minimum {schema['minimum']}")

    if isinstance(instance, list) and "items" in schema:
        item_schema = schema["items"]
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(
                    validate_json_schema(item, item_schema, path=f"{path}[{index}]")
                )

    if isinstance(instance, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")

        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            allowed = set(properties.keys())
            for key in instance:
                if key not in allowed:
                    errors.append(f"{path}: additional property {key!r} is not allowed")

        for key, value in instance.items():
            if key in properties:
                errors.extend(
                    validate_json_schema(value, properties[key], path=f"{path}.{key}")
                )

    return errors


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
        if type_name == "number" and isinstance(instance, (int, float)) and not isinstance(instance, bool):
            return True
    return False
