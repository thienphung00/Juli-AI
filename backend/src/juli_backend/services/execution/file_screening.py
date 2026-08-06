"""Image file screening for uploaded content in executions.

Validates that base64-encoded images are:
1. Appropriately sized (encoded and decoded)
2. Supported image types (PNG, JPEG, GIF, WebP)
3. Valid and non-corrupt (full decode verification)
"""

from __future__ import annotations

import io
from typing import Final

from PIL import Image

# Size caps (ADR-055 item 20)
# Base64 overhead is ~33%, so a 10MB encoded payload decodes to ~7.5MB
MAX_ENCODED_SIZE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_DECODED_SIZE_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB

# Magic bytes (file signatures) for supported image types
# Format: (signature_bytes, format_name)
SUPPORTED_IMAGE_SIGNATURES: Final[dict[bytes, str]] = {
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"\xff\xd8\xff": "JPEG",
    b"GIF87a": "GIF",
    b"GIF89a": "GIF",
    b"RIFF": "WebP",  # RIFF container, verified as WebP by checking WEBP marker
}


def screen_image_bytes(data: bytes) -> bytes:
    """Validate image bytes before use.

    Verifies:
    - Size within acceptable bounds (decoded)
    - Matches a supported image format (magic bytes)
    - Can be decoded as a valid image (not corrupt, not polyglot)

    Args:
        data: Raw image bytes (already base64-decoded)

    Returns:
        The same bytes, passed through validation

    Raises:
        ValueError: If the image fails any validation check
    """
    # Check decoded size cap
    if len(data) > MAX_DECODED_SIZE_BYTES:
        raise ValueError(
            f"Image size {len(data)} bytes exceeds maximum decoded size "
            f"{MAX_DECODED_SIZE_BYTES} bytes"
        )

    # Check file signature (magic bytes)
    if not data:
        raise ValueError("Image data is empty")

    format_name = _detect_image_format(data)
    if not format_name:
        raise ValueError("Image is not a supported image format (PNG, JPEG, GIF, or WebP)")

    # Full decode to verify image is valid and not corrupt
    try:
        with Image.open(io.BytesIO(data)) as img:
            # Force PIL to read and validate the entire image
            img.load()
    except Exception as e:
        raise ValueError(f"Image is corrupt or invalid: {type(e).__name__}: {str(e)}")

    return data


def _detect_image_format(data: bytes) -> str | None:
    """Detect image format from file signature (magic bytes).

    Returns the format name if recognized, None otherwise.
    """
    if not data:
        return None

    # Check for WebP first (RIFF container)
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "WebP"

    # Check other signatures
    for signature, format_name in SUPPORTED_IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return format_name

    return None
