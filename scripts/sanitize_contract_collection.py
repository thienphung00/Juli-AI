#!/usr/bin/env python3
"""Sanitize contract-collection.md for repo commit (issue #294 follow-up).

Redacts live tokens in cURL blocks, moves response payloads into sanitized JSON
blocks, and replaces raw **Response** JSON with a status table.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "docs/integrations/tiktok_api/contract-collection.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from extract_tiktok_fixtures import sanitize_response  # noqa: E402

LIVE_TOKEN_RE = re.compile(r"ROW_[A-Za-z0-9_-]{20,}")
LIVE_BUYER_EMAIL_RE = re.compile(r"@scs2\.tiktok\.com")

RESPONSE_BLOCK_RE = re.compile(
    r"(\*\*Response\*\*\s*\n)(.*?)(\*\*Sanitized response body \(optional\)\*\*\s*\n\s*```json\s*\n)(.*?)(\n```)",
    re.DOTALL,
)


def redact_curl_block(curl: str) -> str:
    curl = re.sub(r"(access_token=)ROW_[^\s&']+", r"\1{access_token}", curl)
    curl = re.sub(r"(shop_cipher=)ROW_[^\s&']+", r"\1{shop_cipher}", curl)
    curl = re.sub(r"(x-tts-access-token:\s*)ROW_[^\s']+", r"\1{access_token}", curl)
    return curl


def _extract_raw_response_json(between: str) -> dict | None:
    for line in between.splitlines():
        stripped = line.strip()
        if stripped.startswith('{"code":'):
            return json.loads(stripped)
    return None


def _response_status_table(code: int, message: str) -> str:
    return (
        "| HTTP status | TikTok `code` | `message` | Notes |\n"
        "|-------------|---------------|-----------|-------|\n"
        f"| 200 | {code} | {message} | Verified via API Testing Tool |"
    )


def _replace_response_block(match: re.Match[str]) -> str:
    between = match.group(2)
    raw = _extract_raw_response_json(between)
    if raw is None:
        return match.group(0)

    code = int(raw.get("code", 0))
    message = str(raw.get("message", "Success"))
    sanitized = json.dumps(sanitize_response(raw), indent=2, ensure_ascii=False)
    return (
        f"**Response**\n\n"
        f"{_response_status_table(code, message)}\n\n"
        f"**Sanitized response body (optional)**\n\n"
        f"```json\n{sanitized}\n```"
    )


def sanitize_markdown(text: str) -> str:
    text = re.sub(
        r"```bash\n(.*?)```",
        lambda m: f"```bash\n{redact_curl_block(m.group(1).strip())}\n```",
        text,
        flags=re.DOTALL,
    )
    return RESPONSE_BLOCK_RE.sub(_replace_response_block, text)


def _assert_no_secrets(text: str) -> None:
    if LIVE_TOKEN_RE.search(text):
        raise ValueError("sanitized contract still contains live ROW_* token/cipher literals")
    if LIVE_BUYER_EMAIL_RE.search(text):
        raise ValueError("sanitized contract still contains buyer proxy email addresses")


def _strip_full_copy_note(text: str) -> str:
    """Remove legacy references to the gitignored full copy artifact."""
    text = re.sub(
        r">\s*> \*\*Sanitized repo copy\.\*\*[^\n]*\n",
        "",
        text,
    )
    text = text.replace(
        "[`contract-collection-full.md`](contract-collection-full.md)",
        "`contract-collection.md`",
    )
    return text


def main() -> int:
    if not CONTRACT_PATH.exists():
        raise SystemExit(f"missing {CONTRACT_PATH}")

    raw = CONTRACT_PATH.read_text(encoding="utf-8")
    cleaned = sanitize_markdown(_strip_full_copy_note(raw))
    _assert_no_secrets(cleaned)

    CONTRACT_PATH.write_text(cleaned, encoding="utf-8")
    print(f"Wrote sanitized contract: {CONTRACT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
