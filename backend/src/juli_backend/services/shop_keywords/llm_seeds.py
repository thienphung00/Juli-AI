"""One model call per shop turns the decomposer's candidates into fewer, cleaner seeds (P100-G).

The deterministic pre-pass (:mod:`.decompose`) strips numbers, noise and fragments; this step
asks the shop's gated client (``shopee_builder.llm.gated_client``: consent ``llm_processing``,
payload allowlist, one ``llm_call_log`` row, purpose ``content_draft``) for a structured read of
the titles: product heads, attributes, groups of similar words and the seeds to look up.

The answer is checked, never trusted:

- a seed whose every word appears in some title is kept as asked;
- a seed with a word no title has is kept only when each such word sits in a similar-word group
  the model tied to a real source title. It is a "từ gần nghĩa": returned to the owner to tick,
  stored disabled, never looked up on its own;
- anything else is dropped;
- item ids are never lost: a title no kept seed covers brings back the deterministic candidates
  that listed it.

Nothing here touches the database; ``seeds.generate`` stores the result.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from juli_backend.services.shop_keywords.collection import normalize_keyword
from juli_backend.services.shop_keywords.decompose import (
    MAX_KEYWORD_LENGTH,
    Candidate,
    Title,
    _tokens,
)
from juli_backend.services.shopee_builder.llm import LLMClient

SCHEMA_NAME = "shop_keyword_seeds"
MAX_TITLES = 300
MAX_CANDIDATES = 150
MAX_SEEDS = 80
MIN_WORDS = 2

SYSTEM = (
    "Bạn gom tiêu đề sản phẩm Shopee của một shop thành từ khóa để tra cứu lượt tìm kiếm. "
    "Chỉ dùng từ có trong tiêu đề. Bỏ số lượng, giá, kích cỡ, khuyến mãi. Mỗi từ khóa 2-5 từ, "
    "là cụm người mua thật sự gõ, không cắt ngang một cụm từ ghép. Mỗi tiêu đề có thể có "
    "thương hiệu riêng. Chỉ đưa vào similar_groups những từ gần nghĩa với một từ trong tiêu đề "
    "và ghi rõ item_id của tiêu đề đó. Trả về JSON đúng schema."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["heads", "attributes", "similar_groups", "seeds"],
    "properties": {
        "heads": {"type": "array", "items": {"type": "string"}},
        "attributes": {"type": "array", "items": {"type": "string"}},
        "similar_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item_id", "source_word", "similar"],
                "properties": {
                    "item_id": {"type": "string"},
                    "source_word": {"type": "string"},
                    "similar": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "seeds": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["keyword", "item_ids"],
                "properties": {
                    "keyword": {"type": "string"},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class Refinement:
    """Checked seeds: ``seeds`` use only title words, ``near`` are "từ gần nghĩa"."""

    seeds: tuple[Candidate, ...]
    near: tuple[Candidate, ...]
    heads: tuple[str, ...]
    attributes: tuple[str, ...]
    model: str


def titles_hash(titles: Sequence[Title], brand: str | None = None) -> str:
    """Stable digest of what the model would be shown; equal hash = nothing to re-ask."""
    rows = sorted(f"{t.item_id}\x1f{t.title.strip()}" for t in titles if t.title.strip())
    return hashlib.sha256("\x1e".join([brand or "", *rows]).encode()).hexdigest()


def _keys(text: str) -> tuple[str, ...]:
    return tuple(t.key for t in _tokens(text))


def _strs(value: Any, limit: int = 60) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()][:limit]


def _prompt(titles: Sequence[Title], candidates: Sequence[Candidate]) -> str:
    lines = [f"{t.item_id}\t{t.title.strip()}" for t in titles[:MAX_TITLES]]
    cands = [c.keyword for c in candidates[:MAX_CANDIDATES]]
    return (
        "Tiêu đề (item_id<TAB>tiêu đề):\n"
        + "\n".join(lines)
        + "\n\nỨng viên đã lọc sẵn:\n"
        + "\n".join(cands)
        + f"\n\nChọn tối đa {MAX_SEEDS} từ khóa."
    )


def _ids_covering(words: tuple[str, ...], title_keys: dict[str, set[str]]) -> tuple[str, ...]:
    return tuple(sorted(i for i, keys in title_keys.items() if set(words) <= keys))


def validate(
    raw: dict[str, Any], titles: Sequence[Title], candidates: Sequence[Candidate], model: str
) -> Refinement:
    """Apply the rules in the module docstring to a model answer."""
    title_keys = {t.item_id: set(_keys(t.title)) for t in titles}
    known_words = set().union(*title_keys.values()) if title_keys else set()
    by_keyword = {normalize_keyword(c.keyword): c for c in candidates}

    similar_words: set[str] = set()
    groups = raw.get("similar_groups")
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or group.get("item_id") not in title_keys:
            continue
        source = _keys(str(group.get("source_word", "")))
        if not source or not set(source) <= title_keys[group["item_id"]]:
            continue
        for word in _strs(group.get("similar")):
            similar_words.update(_keys(word))

    seeds: dict[str, Candidate] = {}
    near: dict[str, Candidate] = {}
    asked_seeds = raw.get("seeds")
    for entry in asked_seeds if isinstance(asked_seeds, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("keyword"), str):
            continue
        keyword = normalize_keyword(entry["keyword"])
        words = _keys(keyword)
        if len(words) < MIN_WORDS or len(keyword) > MAX_KEYWORD_LENGTH:
            continue
        unknown = [w for w in words if w not in known_words]
        if unknown and not all(w in similar_words for w in unknown):
            continue
        asked = tuple(i for i in _strs(entry.get("item_ids"), 500) if i in title_keys)
        ids = tuple(sorted(set(asked))) or _ids_covering(words, title_keys)
        if not ids:
            continue
        known = by_keyword.get(keyword)
        if unknown:
            near.setdefault(keyword, Candidate(keyword, "common_phrase", ids))
        elif keyword not in seeds:
            seeds[keyword] = Candidate(keyword, known.pattern if known else "common_phrase", ids)
        if len(seeds) >= MAX_SEEDS:
            break

    kept = list(seeds.values())
    if not kept:
        kept = list(candidates)  # nothing usable from the model: the deterministic pass stands
    covered = {i for c in kept for i in c.item_ids}
    for c in candidates:
        if not set(c.item_ids) <= covered and normalize_keyword(c.keyword) not in seeds:
            kept.append(c)
            covered.update(c.item_ids)
    return Refinement(
        tuple(kept),
        tuple(near.values()),
        tuple(_strs(raw.get("heads"))),
        tuple(_strs(raw.get("attributes"))),
        model,
    )


async def refine(
    client: LLMClient, titles: Sequence[Title], candidates: Sequence[Candidate]
) -> Refinement:
    """Ask once; ``LLMUnavailable`` propagates so the caller can fall back to the candidates."""
    usable = [t for t in titles if t.title and t.title.strip()]
    raw = await client.complete_json(
        system=SYSTEM,
        user=_prompt(usable, candidates),
        schema_name=SCHEMA_NAME,
        schema=SCHEMA,
    )
    return validate(raw, usable, candidates, client.model)


__all__ = ["Refinement", "refine", "titles_hash", "validate"]
