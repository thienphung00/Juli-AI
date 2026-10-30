"""OpenAI Structured Outputs strict form for tool and output schemas (fast track P76-1, D78).

`to_strict` turns a Pydantic ``model_json_schema()`` render (or a hand-written output
schema) into the subset OpenAI's strict mode accepts, so the model's tool arguments and
structured output are guaranteed to match the declared shape. `strict_problems` is the
independent conformance checker the CI registry test runs over every registered tool.

**The strict rules** (OpenAI Structured Outputs guide, "Supported schemas",
developers.openai.com/api/docs/guides/structured-outputs, read 2026-10-29):

- the root is an ``object`` and never ``anyOf``;
- every object sets ``additionalProperties: false`` and lists EVERY property in
  ``required`` -- an optional field is emulated by a union with ``null``;
- supported keywords: ``type`` / ``properties`` / ``required`` / ``additionalProperties``
  / ``items`` / ``enum`` / ``const`` / ``anyOf`` / ``$ref`` / ``$defs`` / ``description``;
  strings ``pattern`` and ``format`` (date-time, time, date, duration, email, hostname,
  ipv4, ipv6, uuid); numbers ``multipleOf`` / ``maximum`` / ``exclusiveMaximum`` /
  ``minimum`` / ``exclusiveMinimum``; arrays ``minItems`` / ``maxItems``;
- not supported: ``allOf``, ``not``, ``if``/``then``/``else``, ``dependentRequired``,
  ``dependentSchemas``, ``patternProperties``, ``unevaluated*``, ``propertyNames``,
  ``min/maxProperties``, ``contains``, ``uniqueItems``; at most 10 levels of nesting
  and 5000 object properties.

**What this converter does with the rest.**

- ``title``, ``default``, ``examples`` are dropped -- annotation only. A dropped
  ``default`` is restored on the way back in: the field becomes nullable here, and
  `ToolSpec.parse_input` turns the model's explicit ``null`` into the field default.
  A non-null default is told to the model in the description ("null means the
  default, false.").
- ``minLength`` / ``maxLength`` are dropped: the guide does not list them as supported
  string keywords. The bounds stay enforced server-side by the tool's Pydantic input
  model (a violating call is refused as malformed and the model may retry), and the
  model still sees them as a sentence appended to the field's description.
- ``$defs`` are inlined (Pydantic renders nested models as ``$ref``); a recursive
  model raises -- no registered tool has one.
- A discriminated union (``oneOf`` + ``discriminator``, P76-6) becomes ``anyOf``: its
  branches are disjoint by their ``const`` tag, so nothing is widened.
- Anything else outside the supported list raises `StrictSchemaError`. No silent
  degrade: the CI registry test (`tests/unit/test_agent_strict_tool_schemas.py`) is the
  gate (D78.5); the adapter catches the error at request time, logs it, and sends that
  one schema non-strict rather than failing a seller's run.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

__all__ = ["StrictSchemaError", "strict_problems", "to_strict"]

#: OpenAI strict mode's supported ``format`` values for strings.
STRING_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "ipv4", "ipv6", "uuid"}
)
_STRUCTURAL = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "anyOf",
        "$ref",
        "$defs",
        "description",
    }
)
_TYPE_SPECIFIC = frozenset(
    {
        "pattern",
        "format",
        "multipleOf",
        "maximum",
        "exclusiveMaximum",
        "minimum",
        "exclusiveMinimum",
        "minItems",
        "maxItems",
    }
)
#: Every keyword a strict schema may carry.
SUPPORTED_KEYWORDS = _STRUCTURAL | _TYPE_SPECIFIC
#: Annotations dropped without trace (the model loses nothing it needs).
_DROPPED = frozenset({"title", "default", "examples"})
#: Dropped from the wire but kept enforced by Pydantic and stated in the description.
_LENGTH_KEYWORDS = ("minLength", "maxLength")
MAX_NESTING = 10
MAX_PROPERTIES = 5000
_REF_PREFIX = "#/$defs/"


class StrictSchemaError(ValueError):
    """The schema uses a construct OpenAI strict mode cannot express."""


def to_strict(schema: Mapping[str, Any]) -> dict[str, Any]:
    """``schema`` in OpenAI strict form. Pure: the input is never mutated.

    Idempotent, and a schema that already conforms comes back equal to itself.
    Raises `StrictSchemaError` naming the JSON path of the first unconvertible node.
    """
    source = copy.deepcopy(dict(schema))
    defs = source.pop("$defs", {})
    if not isinstance(defs, Mapping):
        raise StrictSchemaError("$defs: must be an object")
    if "anyOf" in source:
        raise StrictSchemaError("$: the root must be an object, not anyOf")
    out = _convert(source, defs, path="$", resolving=())
    if out.get("type") != "object":
        raise StrictSchemaError("$: the root must be an object")
    problems = strict_problems(out)
    if problems:
        raise StrictSchemaError("; ".join(problems))
    return out


def _convert(
    node: Mapping[str, Any],
    defs: Mapping[str, Any],
    *,
    path: str,
    resolving: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise StrictSchemaError(f"{path}: a schema must be an object")
    node = dict(node)
    if "$ref" in node:
        node = _inline_ref(node, defs, path=path, resolving=resolving)
        resolving = (*resolving, str(node.pop("__ref__")))
    if "allOf" in node:
        node = _unwrap_all_of(node, path=path)
    if "discriminator" in node:
        node = _discriminated_union(node, path=path)

    out: dict[str, Any] = {}
    hints = " ".join(hint for hint in (_length_hint(node), _default_hint(node)) if hint)
    for key, value in node.items():
        if key in _DROPPED or key in _LENGTH_KEYWORDS:
            continue
        if key not in SUPPORTED_KEYWORDS:
            raise StrictSchemaError(f"{path}: keyword {key!r} is not supported in strict mode")
        if key == "properties":
            if not isinstance(value, Mapping):
                raise StrictSchemaError(f"{path}.properties: must be an object")
            out[key] = {
                name: _convert(sub, defs, path=f"{path}.{name}", resolving=resolving)
                for name, sub in value.items()
            }
        elif key == "items":
            if not isinstance(value, Mapping):
                raise StrictSchemaError(f"{path}.items: tuple items are not supported")
            out[key] = _convert(value, defs, path=f"{path}[]", resolving=resolving)
        elif key == "anyOf":
            out[key] = [
                _convert(branch, defs, path=f"{path}|{index}", resolving=resolving)
                for index, branch in enumerate(value)
            ]
        elif key == "format" and value not in STRING_FORMATS:
            raise StrictSchemaError(f"{path}: format {value!r} is not supported in strict mode")
        else:
            out[key] = copy.deepcopy(value)
    if hints:
        existing = str(out.get("description", "")).rstrip()
        out["description"] = f"{existing} {hints}".strip()

    if _is_object(out):
        _close_object(out, path=path)
    return out


def _inline_ref(
    node: dict[str, Any],
    defs: Mapping[str, Any],
    *,
    path: str,
    resolving: tuple[str, ...],
) -> dict[str, Any]:
    ref = node.pop("$ref")
    if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
        raise StrictSchemaError(f"{path}: only local '#/$defs/...' references are supported")
    name = ref[len(_REF_PREFIX) :]
    if name in resolving:
        raise StrictSchemaError(f"{path}: recursive reference {ref!r} cannot be inlined")
    if name not in defs:
        raise StrictSchemaError(f"{path}: unresolved reference {ref!r}")
    # Pydantic puts a field's own annotations next to the $ref; they win.
    merged = {**copy.deepcopy(dict(defs[name])), **node}
    merged["__ref__"] = name
    return merged


def _unwrap_all_of(node: dict[str, Any], *, path: str) -> dict[str, Any]:
    branches = node.pop("allOf")
    if not isinstance(branches, list) or len(branches) != 1:
        raise StrictSchemaError(f"{path}: allOf is not supported in strict mode")
    return {**dict(branches[0]), **node}


def _discriminated_union(node: dict[str, Any], *, path: str) -> dict[str, Any]:
    """A Pydantic discriminated union (``oneOf`` + ``discriminator``) as ``anyOf``.

    P76-6: ``ListingEditOps.description_ops`` is a union keyed on ``op``. Pydantic pins
    each branch's tag with a ``const``, so at most one branch matches any value and
    ``anyOf`` accepts exactly what ``oneOf`` did; the ``discriminator`` itself is an
    annotation and is dropped. A ``discriminator`` without a ``oneOf`` is refused.
    """
    branches = node.pop("oneOf", None)
    node.pop("discriminator")
    if not isinstance(branches, list) or "anyOf" in node:
        raise StrictSchemaError(f"{path}: discriminator without a oneOf union is not supported")
    return {**node, "anyOf": branches}


def _length_hint(node: Mapping[str, Any]) -> str:
    low, high = node.get("minLength"), node.get("maxLength")
    if low is not None and high is not None:
        return f"Must be {low}-{high} characters long."
    if low is not None:
        return f"Must be at least {low} characters long."
    if high is not None:
        return f"Must be at most {high} characters long."
    return ""


def _default_hint(node: Mapping[str, Any]) -> str:
    """A dropped non-null default, told to the model: its ``null`` now means it."""
    if node.get("default") is None:
        return ""
    return f"null means the default, {json.dumps(node['default'], ensure_ascii=False)}."


def _is_object(node: Mapping[str, Any]) -> bool:
    kind = node.get("type")
    return kind == "object" or (isinstance(kind, list) and "object" in kind)


def _close_object(out: dict[str, Any], *, path: str) -> None:
    extra = out.get("additionalProperties", False)
    if extra is not False:
        raise StrictSchemaError(
            f"{path}: an open object (additionalProperties={extra!r}) cannot be strict; "
            "declare a fixed set of properties"
        )
    properties: dict[str, Any] = out.setdefault("properties", {})
    declared = set(out.get("required", ()))
    for name, sub in properties.items():
        if name not in declared:
            properties[name] = _nullable(sub)
    out["required"] = list(properties)
    out["additionalProperties"] = False


def _nullable(node: dict[str, Any]) -> dict[str, Any]:
    """``node`` widened to also accept ``null`` (strict mode's optional field)."""
    branches = node.get("anyOf")
    if isinstance(branches, list):
        if not any(_accepts_null(branch) for branch in branches):
            node["anyOf"] = [*branches, {"type": "null"}]
        return node
    if _accepts_null(node):
        return node
    kind = node.get("type")
    if "enum" not in node and "const" not in node:
        if isinstance(kind, str):
            node["type"] = [kind, "null"]
            return node
        if isinstance(kind, list):
            node["type"] = [*kind, "null"]
            return node
    description = node.pop("description", None)
    wrapped: dict[str, Any] = {"anyOf": [node, {"type": "null"}]}
    if description is not None:
        wrapped["description"] = description
    return wrapped


def _accepts_null(node: Mapping[str, Any]) -> bool:
    kind = node.get("type")
    return kind == "null" or (isinstance(kind, list) and "null" in kind)


# ---------------------------------------------------------------------------
# Conformance checker
# ---------------------------------------------------------------------------


def strict_problems(schema: Mapping[str, Any]) -> list[str]:
    """Every way ``schema`` breaks OpenAI strict mode; empty when it conforms.

    Independent of `to_strict` (it re-walks the result), so the registry test checks
    the converter's output against the rules rather than against the converter.
    """
    problems: list[str] = []
    if schema.get("type") != "object" or "anyOf" in schema:
        problems.append("$: the root must be an object, not anyOf")
    defs: Mapping[str, Any] = schema.get("$defs", {})
    count = 0

    def check(node: Any, path: str, depth: int, seen: tuple[str, ...]) -> None:
        nonlocal count
        if not isinstance(node, Mapping):
            problems.append(f"{path}: a schema must be an object")
            return
        problems.extend(
            f"{path}: unsupported keyword {key!r}" for key in node if key not in SUPPORTED_KEYWORDS
        )
        if node.get("format") is not None and node["format"] not in STRING_FORMATS:
            problems.append(f"{path}: unsupported format {node['format']!r}")
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref[len(_REF_PREFIX) :] if ref.startswith(_REF_PREFIX) else ""
            if name not in defs:
                problems.append(f"{path}: unresolved reference {ref!r}")
            elif name not in seen:
                check(defs[name], f"{path}->{name}", depth, (*seen, name))
        if _is_object(node):
            if depth >= MAX_NESTING:
                problems.append(f"{path}: nesting deeper than {MAX_NESTING} levels")
            properties = node.get("properties")
            if not isinstance(properties, Mapping):
                problems.append(f"{path}: an object must declare properties")
                properties = {}
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false")
            required = node.get("required")
            if not isinstance(required, list) or set(required) != set(properties):
                problems.append(f"{path}: every property must be listed in required")
            count += len(properties)
            for name, sub in properties.items():
                check(sub, f"{path}.{name}", depth + 1, seen)
        if "items" in node:
            check(node["items"], f"{path}[]", depth, seen)
        for index, branch in enumerate(node.get("anyOf") or ()):
            check(branch, f"{path}|{index}", depth, seen)

    check(schema, "$", 0, ())
    if count > MAX_PROPERTIES:
        problems.append(f"$: {count} object properties exceed {MAX_PROPERTIES}")
    return problems
