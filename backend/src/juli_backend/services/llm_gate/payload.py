"""What may leave for OpenAI: request shape, ZDR flags, input kinds, minimisation (ADR-116 §5).

Pure functions over a request the gate is about to send; no I/O. :func:`inspect_request`
either returns the body to send and the consent scopes its inputs need, or raises
:class:`PayloadRefused` with a machine-readable reason. The gate logs the refusal and
sends nothing.

THE SHAPE IS AN ALLOWLIST (fail closed). A ``/v1/responses`` body may carry only the
top-level keys in :data:`RESPONSES_KEYS`; every ``input`` item is a role message, a
``function_call`` or a ``function_call_output``; every content part is ``input_text``,
``output_text`` or ``input_image``. A transcription form carries only
:data:`TRANSCRIPTION_FIELDS` and one ``file``. Anything else is a request nobody has
reviewed, so it is refused rather than guessed at (``payload_shape``). The endpoints
themselves are allowlisted in the gate (``/v1/responses``, ``/v1/audio/transcriptions``).

ZDR FLAGS. A responses body must say ``store: false`` and must not carry
``previous_response_id``, ``background`` or ``conversation`` (no provider-side state).
The transcription endpoint has no ``store`` field: nothing to check there.

INPUT KINDS -> CONSENT SCOPES (grill D4 addendum: consent is split by input).

- text (instructions, text parts, tool results, the transcription glossary)
  -> ``llm_processing``;
- an ``input_image`` part -> ``llm_images`` -- except a ``data:`` image in a call whose
  purpose reads video / LIVE keyframes, which is a frame -> ``llm_media``;
- audio (the transcription endpoint) -> ``llm_media``;
- an image URL written inside text -> ``llm_images`` when the shop granted it; when it
  did not, the URL is replaced by :data:`IMAGE_REMOVED` and nothing is required (owner
  decision: images, image URLs and audio never leave for a text-only shop such as Ory).

MINIMISATION (T3). Every text value that is a JSON object / array (tool results, the
opening context, replayed tool-call arguments) is parsed and any key for which
:func:`is_forbidden_key` holds is dropped at any depth: the shop's name, ids and
cipher, every buyer / recipient field, user ids, and tokens / credentials. Listing
content, attributes, aggregate metrics and the shop's own rules are untouched (none of
their keys match). Then the shop's own identifiers (its Juli id and TikTok / Shopee
shop ids) are replaced by :data:`SHOP_REDACTED` wherever they appear in text as a whole
token. The shop *name* is not scrubbed from free text: it is usually the brand, which
is listing content. Tool *schemas* (``tools[].parameters``) and the output schema
(``text.format``) are not data and pass as they are. Every text first goes through the
D68.2 ``deidentify_text`` (e-mails, contact numbers, buyer / contact keys) -- here, at the
one door, so no path can skip it (the clients also call it; it is safe twice).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from juli_backend.core.privacy import deidentify_text

LLM_PROCESSING = "llm_processing"
LLM_IMAGES = "llm_images"
LLM_MEDIA = "llm_media"
#: The consent scopes an OpenAI call can need, in the order a refusal names them.
LLM_SCOPES: tuple[str, ...] = (LLM_PROCESSING, LLM_IMAGES, LLM_MEDIA)

OPENAI_BASE_URL = "https://api.openai.com"
RESPONSES_ENDPOINT = "/v1/responses"
TRANSCRIPTIONS_ENDPOINT = "/v1/audio/transcriptions"

RESPONSES_KEYS = frozenset(
    {
        "model",
        "instructions",
        "input",
        "tools",
        "max_output_tokens",
        "temperature",
        "store",
        "stream",
        "tool_choice",
        "text",
    }
)
#: Keys that would keep state at OpenAI; each has its own refusal reason.
STATEFUL_KEYS: tuple[str, ...] = ("previous_response_id", "background", "conversation")
TRANSCRIPTION_FIELDS = frozenset(
    {"model", "language", "prompt", "response_format", "timestamp_granularities[]", "temperature"}
)
_MESSAGE_ROLES = frozenset({"user", "assistant", "system", "developer"})
_TEXT_PARTS = frozenset({"input_text", "output_text"})
_IMAGE_PART_KEYS = frozenset({"type", "image_url", "detail"})

REASON_SHAPE = "payload_shape"
REASON_STORE = "zdr_store"

IMAGE_REMOVED = "[ảnh đã ẩn]"
SHOP_REDACTED = "[shop]"
#: An identifier shorter than this is too likely to collide with ordinary text.
_MIN_IDENTIFIER = 6

#: Exact keys (lower case) that never leave: the shop's identity, user ids, credentials.
FORBIDDEN_KEYS = frozenset(
    {
        "shop_name",
        "shop_id",
        "shop_ids",
        "shop_cipher",
        "cipher",
        "bound_shop_cipher",
        "tiktok_shop_id",
        "tiktok_numeric_shop_id",
        "shopee_shop_id",
        "seller_id",
        "seller_name",
        "merchant_id",
        "merchant_authorization_id",
        "open_id",
        "user_id",
        "user_ids",
        "access_token",
        "refresh_token",
        "token",
        "id_token",
        "api_key",
        "app_key",
        "app_secret",
        "client_secret",
        "secret",
        "password",
        "authorization",
        "credential",
        "credentials",
    }
)
#: Any key starting with one of these is buyer / recipient data.
FORBIDDEN_PREFIXES: tuple[str, ...] = ("buyer", "recipient")
#: Any key ending with one of these is a credential.
FORBIDDEN_SUFFIXES: tuple[str, ...] = ("_token", "_secret", "_cipher", "_password", "_api_key")

#: An http(s) URL that points at an image: an image extension, or a known image CDN.
IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"'<>)\]]+?"
    r"(?:\.(?:jpe?g|png|webp|gif|bmp|heic|avif)(?:\?[^\s\"'<>)\]]*)?"
    r"|(?:ibyteimg|byteimg|tiktokcdn|tiktokcdn-us|muscdn|susercontent|alicdn)"
    r"[^\s\"'<>)\]]*)",
    re.IGNORECASE,
)
DATA_IMAGE_RE = re.compile(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)


class PayloadRefused(Exception):
    """The request may not be sent; ``reason`` is the ``llm_call_log.refusal_reason``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class InspectedRequest:
    """A request the gate may send once the shop holds every scope in ``required``."""

    body: dict[str, Any]
    required: frozenset[str]
    #: Image URLs replaced in text because the shop has no ``llm_images`` grant.
    stripped_image_urls: int = 0


def is_forbidden_key(key: str) -> bool:
    """``True`` for a key whose value never goes to OpenAI (see module docstring)."""
    lowered = key.strip().lower()
    return (
        lowered in FORBIDDEN_KEYS
        or lowered.startswith(FORBIDDEN_PREFIXES)
        or lowered.endswith(FORBIDDEN_SUFFIXES)
    )


def drop_forbidden_keys(value: Any) -> Any:
    """A copy of JSON-like ``value`` without any forbidden key, at any depth."""
    if isinstance(value, Mapping):
        return {
            str(k): drop_forbidden_keys(v) for k, v in value.items() if not is_forbidden_key(str(k))
        }
    if isinstance(value, list | tuple):
        return [drop_forbidden_keys(item) for item in value]
    return value


class _TextCleaner:
    """Applies minimisation to every text value of one request; counts what it did."""

    def __init__(self, *, images_allowed: bool, shop_identifiers: Iterable[str]) -> None:
        self.images_allowed = images_allowed
        self.image_urls_seen = 0
        self.image_urls_stripped = 0
        self.has_text = False
        # Longest first, so an id containing a shorter one is replaced whole.
        self._identifiers = [
            re.compile(rf"(?<![\w-]){re.escape(i)}(?![\w-])", re.IGNORECASE)
            for i in sorted(
                {i.strip() for i in shop_identifiers if len(i.strip()) >= _MIN_IDENTIFIER},
                key=len,
                reverse=True,
            )
        ]

    def clean(self, text: str) -> str:
        if text.strip():
            self.has_text = True
        out = self._drop_keys_in_json(deidentify_text(text))
        for identifier in self._identifiers:
            out = identifier.sub(SHOP_REDACTED, out)
        return self._images_in_text(out)

    @staticmethod
    def _drop_keys_in_json(text: str) -> str:
        stripped = text.lstrip()
        if stripped[:1] not in ("{", "["):
            return text
        try:
            parsed = json.loads(text)
        except ValueError:
            return text
        if not isinstance(parsed, dict | list):
            return text
        cleaned = drop_forbidden_keys(parsed)
        if cleaned == parsed:
            return text
        return json.dumps(cleaned, ensure_ascii=False)

    def _images_in_text(self, text: str) -> str:
        found = len(IMAGE_URL_RE.findall(text)) + len(DATA_IMAGE_RE.findall(text))
        if not found:
            return text
        self.image_urls_seen += found
        if self.images_allowed:
            return text
        self.image_urls_stripped += found
        return IMAGE_URL_RE.sub(IMAGE_REMOVED, DATA_IMAGE_RE.sub(IMAGE_REMOVED, text))


def inspect_responses_body(
    body: Mapping[str, Any],
    *,
    frames_purpose: bool,
    images_allowed: bool,
    shop_identifiers: Iterable[str] = (),
) -> InspectedRequest:
    """Check and minimise a ``/v1/responses`` body (module docstring)."""
    for key in STATEFUL_KEYS:
        if key in body:
            raise PayloadRefused(f"zdr_{key}")
    if body.get("store") is not False:
        raise PayloadRefused(REASON_STORE)
    unknown = set(body) - RESPONSES_KEYS
    if unknown:
        raise PayloadRefused(REASON_SHAPE)
    cleaner = _TextCleaner(images_allowed=images_allowed, shop_identifiers=shop_identifiers)
    required: set[str] = set()
    out = dict(body)
    instructions = body.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str):
            raise PayloadRefused(REASON_SHAPE)
        out["instructions"] = cleaner.clean(instructions)
    items = body.get("input", [])
    if not isinstance(items, list):
        raise PayloadRefused(REASON_SHAPE)
    out["input"] = [
        _inspect_item(item, cleaner=cleaner, required=required, frames_purpose=frames_purpose)
        for item in items
    ]
    if cleaner.has_text:
        required.add(LLM_PROCESSING)
    if cleaner.image_urls_seen and images_allowed:
        required.add(LLM_IMAGES)
    return InspectedRequest(
        body=out, required=frozenset(required), stripped_image_urls=cleaner.image_urls_stripped
    )


def _inspect_item(
    item: Any, *, cleaner: _TextCleaner, required: set[str], frames_purpose: bool
) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PayloadRefused(REASON_SHAPE)
    item_type = item.get("type")
    if item_type == "function_call":
        if set(item) - {"type", "call_id", "name", "arguments"}:
            raise PayloadRefused(REASON_SHAPE)
        return {**item, "arguments": cleaner.clean(str(item.get("arguments") or "{}"))}
    if item_type == "function_call_output":
        if set(item) - {"type", "call_id", "output"}:
            raise PayloadRefused(REASON_SHAPE)
        return {**item, "output": cleaner.clean(str(item.get("output") or ""))}
    if item_type not in (None, "message") or item.get("role") not in _MESSAGE_ROLES:
        raise PayloadRefused(REASON_SHAPE)
    if set(item) - {"type", "role", "content"}:
        raise PayloadRefused(REASON_SHAPE)
    content = item.get("content")
    if isinstance(content, str):
        return {**item, "content": cleaner.clean(content)}
    if not isinstance(content, list):
        raise PayloadRefused(REASON_SHAPE)
    return {
        **item,
        "content": [
            _inspect_part(part, cleaner=cleaner, required=required, frames_purpose=frames_purpose)
            for part in content
        ],
    }


def _inspect_part(
    part: Any, *, cleaner: _TextCleaner, required: set[str], frames_purpose: bool
) -> dict[str, Any]:
    if not isinstance(part, Mapping):
        raise PayloadRefused(REASON_SHAPE)
    part_type = part.get("type")
    if part_type in _TEXT_PARTS:
        if set(part) - {"type", "text", "annotations"}:
            raise PayloadRefused(REASON_SHAPE)
        return {**part, "text": cleaner.clean(str(part.get("text") or ""))}
    if part_type == "input_image":
        if set(part) - _IMAGE_PART_KEYS or not isinstance(part.get("image_url"), str):
            raise PayloadRefused(REASON_SHAPE)
        is_frame = frames_purpose and str(part["image_url"]).startswith("data:")
        required.add(LLM_MEDIA if is_frame else LLM_IMAGES)
        return dict(part)
    raise PayloadRefused(REASON_SHAPE)


def inspect_transcription_form(
    data: Mapping[str, Any],
    files: Mapping[str, Any],
    *,
    shop_identifiers: Iterable[str] = (),
) -> InspectedRequest:
    """Check and minimise a transcription form. No ``store`` field exists on this
    endpoint, so there is no ZDR flag to check; audio always needs ``llm_media``."""
    if set(data) - TRANSCRIPTION_FIELDS or set(files) != {"file"}:
        raise PayloadRefused(REASON_SHAPE)
    cleaner = _TextCleaner(images_allowed=False, shop_identifiers=shop_identifiers)
    out = dict(data)
    if isinstance(data.get("prompt"), str):
        out["prompt"] = cleaner.clean(data["prompt"])
    required = {LLM_MEDIA}
    if cleaner.has_text:
        required.add(LLM_PROCESSING)
    return InspectedRequest(body=out, required=frozenset(required))


__all__ = [
    "DATA_IMAGE_RE",
    "FORBIDDEN_KEYS",
    "FORBIDDEN_PREFIXES",
    "FORBIDDEN_SUFFIXES",
    "IMAGE_REMOVED",
    "IMAGE_URL_RE",
    "LLM_IMAGES",
    "LLM_MEDIA",
    "LLM_PROCESSING",
    "LLM_SCOPES",
    "OPENAI_BASE_URL",
    "RESPONSES_ENDPOINT",
    "SHOP_REDACTED",
    "TRANSCRIPTIONS_ENDPOINT",
    "InspectedRequest",
    "PayloadRefused",
    "drop_forbidden_keys",
    "inspect_responses_body",
    "inspect_transcription_form",
    "is_forbidden_key",
]
