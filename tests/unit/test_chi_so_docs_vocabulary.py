"""D31.8: one vocabulary across the UI, the Ops metrics guide and the seller guide.

Both guides open with the same glossary ("## Bảng thuật ngữ"): the same rows and the
same label column (the Ops guide adds a "Cách tính" column). Every label must be an
on-screen string (it appears verbatim somewhere in ``apps/demo/src``), and the seller
guide must not leak backend or team vocabulary.
"""

from __future__ import annotations

import html
import re
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "chi-so"
OPS_DOC = DOCS / "ops-huong-dan-chi-so.md"
SELLER_DOC = DOCS / "nguoi-ban-huong-dan-chi-so.md"
UI_SRC = ROOT / "apps" / "demo" / "src"
GLOSSARY_HEADING = "## Bảng thuật ngữ"

# TODO(P24): remove once fasttrack/p24-strength (D31.7 change strength) merges and
# these strings are on screen; until then they are the agreed copy, not UI text yet.
PENDING_D31_7_LABELS: frozenset[str] = frozenset(
    {
        "Thay đổi rõ",
        "Có thể thay đổi",
        "Đạt · chưa chắc chắn",
    }
)

# Words the seller guide must never contain (case-insensitive, whole words).
BANNED_WORDS: tuple[str, ...] = (
    "API",
    "endpoint",
    "backend",
    "webhook",
    "Ops",
    "band",
    "p10",
    "p90",
    "stdev",
    "RLS",
    "CV",
    "window",
    "tunable",
    "database",
)
BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("decision code (D2x/D3x)", re.compile(r"\bD[23]\d(?:\.\d+)?\b")),
    ("snake_case identifier", re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")),
    ("stdev / root symbol", re.compile(r"[σ√]")),
)


def _glossary_labels(path: Path) -> list[str]:
    """The first column of the first table under the glossary heading."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(GLOSSARY_HEADING)
    rows: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            if rows:
                break
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        rows.append(stripped)
    assert len(rows) > 2, f"{path.name}: no glossary table"
    labels: list[str] = []
    for row in rows[2:]:  # skip the header and the |---| separator
        cell = re.split(r"(?<!\\)\|", row.strip("|"))[0].strip()
        labels.append(cell.replace("**", "").replace("`", "").strip())
    return labels


@cache
def _ui_text() -> str:
    parts: list[str] = []
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix in {".ts", ".tsx"} and "__tests__" not in path.parts:
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_both_guides_share_the_same_glossary_labels() -> None:
    ops = _glossary_labels(OPS_DOC)
    seller = _glossary_labels(SELLER_DOC)
    assert len(ops) == len(set(ops)), "duplicate label in the Ops glossary"
    assert ops == seller, (
        f"glossaries differ: only Ops {sorted(set(ops) - set(seller))}, "
        f"only seller {sorted(set(seller) - set(ops))}"
    )


def test_ops_glossary_has_the_extra_cach_tinh_column() -> None:
    text = OPS_DOC.read_text(encoding="utf-8")
    assert "| Nhãn trên màn hình | Ý nghĩa | Cách tính |" in text
    assert "| Nhãn trên màn hình | Ý nghĩa |" in SELLER_DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize("label", _glossary_labels(OPS_DOC))
def test_every_label_is_on_screen(label: str) -> None:
    if label in PENDING_D31_7_LABELS:
        pytest.skip("D31.7 label pending fasttrack/p24-strength (TODO remove allowlist)")
    ui = _ui_text()
    assert label in ui or html.escape(label, quote=False) in ui, (
        f"glossary label {label!r} is not in apps/demo/src verbatim"
    )


# Labels retired by the vocabulary standardisation (V1–V10); neither guide may use them.
RETIRED_LABELS: tuple[str, ...] = (
    "Hiển thị/ngày",  # V1 → "Lượt hiển thị/ngày" (capital H: the old standalone label)
    "Lượt hiển thị sản phẩm",
    "Tỉ lệ",  # V2
    "Lượt bấm",  # V3
    "Gần đạt",  # V5
    "Chưa kết luận",
    "Dao động thường",  # V7
    "Biến thiên hiển thị",
    "Ngưỡng biến động",
    "Ngưỡng bạn đặt",  # V8
    "Phê duyệt",  # V10
)


@pytest.mark.parametrize("doc", [OPS_DOC, SELLER_DOC], ids=["ops", "seller"])
def test_guides_use_no_retired_label(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    assert [label for label in RETIRED_LABELS if label in text] == []


def test_seller_guide_has_no_backend_or_team_terms() -> None:
    text = SELLER_DOC.read_text(encoding="utf-8")
    hits: list[str] = []
    for word in BANNED_WORDS:
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, flags=re.IGNORECASE):
            hits.append(word)
    for name, pattern in BANNED_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append(f"{name}: {match.group(0)!r}")
    assert not hits, f"seller guide contains banned terms: {hits}"
