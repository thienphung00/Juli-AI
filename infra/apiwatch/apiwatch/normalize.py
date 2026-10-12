"""Shared, pure normalization helpers: turn the platforms' param trees, flat
depth-marked lists, example payloads and markdown tables into ``{field_path: spec}``
maps with a stable spelling.

Field path spelling: ``a.b`` for object members, ``a[].b`` for members of the
objects in array ``a``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

_PLACEHOLDER = re.compile(r"\{[^}]*\}")
_VERSION_SEGMENT = re.compile(r"/(20\d{4})(?=/)")
_DEPRECATION = re.compile(
    r"\b(deprecat\w*|sunset\w*|will be offline|coming offline|offline soon|retire[ds]?"
    r"|no longer (?:be )?(?:supported|maintained|available)|be removed|decommission\w*)\b",
    re.IGNORECASE,
)


def norm_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    return text or "?"


def is_array_type(type_name: str) -> bool:
    return type_name.startswith("[]") or type_name.endswith("[]") or type_name == "array"


def as_required(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"y", "yes", "true", "1", "required"}


def path_template(path: str) -> str:
    """``/product/202309/products/{product_id}`` -> ``/product/202309/products/{}``."""
    text = _PLACEHOLDER.sub("{}", path.strip())
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def versionless(path: str) -> str:
    """Drop the TikTok six-digit version segment: ``/product/{v}/products``."""
    return _VERSION_SEGMENT.sub("/{v}", path_template(path))


def looks_deprecated(*texts: str | None) -> bool:
    return any(_DEPRECATION.search(t or "") for t in texts)


def short_hash(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def _child_prefix(prefix: str, name: str, type_name: str) -> str:
    base = f"{prefix}.{name}" if prefix else name
    return base + "[]" if is_array_type(type_name) else base


def flatten_tree(
    params: Iterable[dict[str, Any]] | None,
    *,
    prefix: str = "",
    with_required: bool = True,
) -> dict[str, dict[str, Any]]:
    """Nested ``[{name, type, required, children: [...]}]`` (Shopee) -> path map."""
    out: dict[str, dict[str, Any]] = {}
    for param in params or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip()
        if not name:
            continue
        type_name = norm_type(param.get("type"))
        path = f"{prefix}.{name}" if prefix else name
        spec: dict[str, Any] = {"type": type_name}
        if with_required:
            spec["required"] = as_required(param.get("required"))
        out[path] = spec
        children = param.get("children")
        if children:
            out.update(
                flatten_tree(
                    children,
                    prefix=_child_prefix(prefix, name, type_name),
                    with_required=with_required,
                )
            )
    return out


def flatten_caret_list(
    params: Iterable[dict[str, Any]] | None,
    *,
    with_required: bool = True,
) -> dict[str, dict[str, Any]]:
    """Flat list where depth is a ``^`` prefix on the name (TikTok api_meta) -> path map.

    ``[data, ^audit, ^^status, ^skus, ^^id]`` -> ``data``, ``data.audit``,
    ``data.audit.status``, ``data.skus``, ``data.skus[].id``.
    """
    out: dict[str, dict[str, Any]] = {}
    stack: list[str] = []  # stack[d] = child prefix for depth d+1
    for param in params or []:
        if not isinstance(param, dict):
            continue
        raw = str(param.get("name") or "")
        depth = len(raw) - len(raw.lstrip("^"))
        name = raw.lstrip("^").strip()
        if not name:
            continue
        del stack[depth:]
        # A malformed depth jump attaches to the deepest known parent.
        prefix = stack[-1] if stack else ""
        type_name = norm_type(param.get("type"))
        path = f"{prefix}.{name}" if prefix else name
        spec: dict[str, Any] = {"type": type_name}
        if with_required:
            spec["required"] = as_required(param.get("required"))
        # Duplicate names at the same path (docs typos) keep the first spelling.
        out.setdefault(path, spec)
        stack.append(_child_prefix(prefix, name, type_name))
    return out


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        inner = {_json_type(v) for v in value}
        return "[]" + (inner.pop() if len(inner) == 1 else "any")
    if isinstance(value, dict):
        return "object"
    return "null"


def json_field_paths(value: Any, *, prefix: str = "") -> dict[str, dict[str, Any]]:
    """Example payload -> path map with types inferred from the sample values."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        for key in value:
            path = f"{prefix}.{key}" if prefix else str(key)
            child = value[key]
            out[path] = {"type": _json_type(child)}
            if isinstance(child, dict):
                out.update(json_field_paths(child, prefix=path))
            elif isinstance(child, list):
                for item in child:
                    if isinstance(item, dict):
                        out.update(json_field_paths(item, prefix=path + "[]"))
    return out


_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
_TREE_MARK = re.compile(r"^[\s└├│─\- ]*")


def markdown_table_fields(markdown: str) -> dict[str, dict[str, Any]]:
    """Parameter tables in a doc page (TikTok webhook pages) -> path map.

    Rows look like ``| name | sample | description |``; nesting is drawn with ``└``
    marks before the name (one per level). A sample of ``[]object`` / ``object``
    marks a container.
    """
    out: dict[str, dict[str, Any]] = {}
    stack: list[str] = []
    for line in (markdown or "").splitlines():
        match = _TABLE_ROW.match(line.strip())
        if not match:
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if not cells or set(cells[0]) <= set("-: "):
            continue
        raw = cells[0].replace("**", "").replace("`", "")
        depth = raw.count("└")
        name = _TREE_MARK.sub("", raw).strip()
        if not name or " " in name or name.lower().startswith(("parameter", "properties", "field")):
            continue
        sample = cells[1] if len(cells) > 1 else ""
        type_name = sample if sample in {"object", "[]object", "[]string", "[]int"} else "?"
        del stack[depth:]
        prefix = stack[-1] if stack and depth else ""
        path = f"{prefix}.{name}" if prefix else name
        out.setdefault(path, {"type": type_name})
        stack.append(_child_prefix(prefix, name, type_name) if type_name != "?" else path)
    return out


def extract_json_blocks(markdown: str) -> list[Any]:
    blocks = re.findall(r"```(?:json|JSON)?\s*\n(.*?)```", markdown or "", flags=re.DOTALL)
    out = []
    for block in blocks:
        try:
            out.append(json.loads(block))
        except ValueError:
            continue
    return out


_API_PATH = re.compile(r"/[a-z_]+/20\d{4}/[A-Za-z0-9_/{}.-]*[A-Za-z0-9_}]")


def api_path_mentions(text: str) -> list[str]:
    """TikTok API paths mentioned in free text, as path templates."""
    return sorted({path_template(m) for m in _API_PATH.findall(text or "")})
