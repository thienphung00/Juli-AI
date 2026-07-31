"""Build thin JSON catalogs from TikTok corpus markdown front matter."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_CORPORA_ROOT = Path("/Users/macos/Juli-AI-local/tiktok-corpora")
CORPUS_NAMES = ("business", "academy", "partner")

REQUIRED_ENTRY_FIELDS = frozenset(
    {
        "corpus",
        "path",
        "title",
        "url",
        "slug",
        "section",
        "nav_path",
        "page_kind",
        "last_crawled",
    }
)

OPTIONAL_ENTRY_FIELDS = frozenset({"method", "api_path", "version"})


def build_corpus_root() -> Path:
    override = os.environ.get("JULI_TIKTOK_CORPORA_ROOT")
    if override:
        return Path(override)
    return DEFAULT_CORPORA_ROOT


def should_skip_path(rel_path: Path) -> bool:
    return "_raw" in rel_path.parts


def parse_front_matter(content: str) -> tuple[dict[str, str], str]:
    content = content.lstrip("\ufeff")
    if not content.startswith("---"):
        return {}, content

    closing = content.find("\n---", 3)
    if closing == -1:
        return {}, content

    fm_block = content[3:closing].strip()
    body = content[closing + 4 :].lstrip("\n")
    fields: dict[str, str] = {}

    for line in fm_block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, raw_value = stripped.partition(":")
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        fields[key] = value

    return fields, body


def _first_section(rel_path: Path) -> str:
    parts = rel_path.parts
    if len(parts) > 1:
        return parts[0]
    return ""


def _entry_from_front_matter(corpus: str, rel_path: Path, fields: dict[str, str]) -> dict[str, str]:
    slug = fields.get("slug") or fields.get("knowledge_id") or rel_path.stem
    nav_path = fields.get("nav_path") or fields.get("breadcrumb", "")

    entry: dict[str, str] = {
        "corpus": corpus,
        "path": rel_path.as_posix(),
        "title": fields.get("title", ""),
        "url": fields.get("url", ""),
        "slug": slug,
        "section": fields.get("section") or _first_section(rel_path),
        "nav_path": nav_path,
        "page_kind": fields.get("page_kind", "article"),
        "last_crawled": fields.get("last_crawled", ""),
    }

    for field in OPTIONAL_ENTRY_FIELDS:
        value = fields.get(field)
        if value:
            entry[field] = value

    return entry


def build_catalog_for_corpus(corpus: str, corpus_dir: Path) -> dict[str, Any]:
    entries: list[dict[str, str]] = []

    if corpus_dir.is_dir():
        for md_path in sorted(corpus_dir.rglob("*.md")):
            rel_path = md_path.relative_to(corpus_dir)
            if should_skip_path(rel_path):
                continue

            content = md_path.read_text(encoding="utf-8")
            fields, _body = parse_front_matter(content)
            entries.append(_entry_from_front_matter(corpus, rel_path, fields))

    return {
        "corpus": corpus,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "corpus_dir": corpus_dir.as_posix(),
        "entry_count": len(entries),
        "entries": entries,
    }


def build_all_catalogs(corpus_root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = corpus_root or build_corpus_root()
    return {
        corpus: build_catalog_for_corpus(corpus, root / f"{corpus}_documents")
        for corpus in CORPUS_NAMES
    }


def write_catalogs(output_dir: Path, corpus_root: Path | None = None) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    for corpus, catalog in build_all_catalogs(corpus_root).items():
        out_path = output_dir / f"{corpus}-catalog.json"
        out_path.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        counts[corpus] = catalog["entry_count"]

    return counts
