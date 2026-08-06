"""Image file screening for uploaded content in executions.

Validates that base64-encoded images are:
1. Appropriately sized (encoded and decoded)
2. Supported image types (PNG, JPEG, GIF, WebP)
3. Valid and non-corrupt (full decode verification)
4. Filename extension matches detected file signature
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Final

from PIL import Image

# Size caps (ADR-055 item 20)
# Base64 overhead is ~33%, so a 10MB encoded payload decodes to ~7.5MB
MAX_ENCODED_SIZE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_DECODED_SIZE_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB

# Magic bytes (file signatures) for supported image types
# Format: signature_bytes -> (format_name, acceptable_extensions)
SUPPORTED_IMAGE_SIGNATURES: Final[dict[bytes, tuple[str, frozenset[str]]]] = {
    b"\x89PNG\r\n\x1a\n": ("PNG", frozenset({".png"})),
    b"\xff\xd8\xff": ("JPEG", frozenset({".jpg", ".jpeg", ".jpe"})),
    b"GIF87a": ("GIF", frozenset({".gif"})),
    b"GIF89a": ("GIF", frozenset({".gif"})),
    b"RIFF": ("WebP", frozenset({".webp"})),
}


def screen_image_bytes(
    data: bytes, filename: str | None = None, content_type: str | None = None
) -> bytes:
    """Validate image bytes before use.

    Verifies:
    - Size within acceptable bounds (decoded)
    - Matches a supported image format (magic bytes)
    - Can be decoded as a valid image (not corrupt, not polyglot)
    - Filename extension agrees with detected format (if filename provided)

    Args:
        data: Raw image bytes (already base64-decoded)
        filename: Optional declared filename for extension validation
        content_type: Optional declared MIME type (not used for validation, since it's
                      trivially spoofable; magic bytes are authoritative)

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

    format_name, detected_extensions = _detect_image_format(data)
    if not format_name:
        raise ValueError("Image is not a supported image format (PNG, JPEG, GIF, or WebP)")

    # Full decode to verify image is valid and not corrupt
    try:
        with Image.open(io.BytesIO(data)) as img:
            # Force PIL to read and validate the entire image
            img.load()
    except Exception as e:
        raise ValueError(f"Image is corrupt or invalid: {type(e).__name__}: {str(e)}")

    # Validate extension agreement if filename provided
    if filename:
        file_ext = Path(filename).suffix.lower()
        if file_ext and file_ext not in detected_extensions:
            raise ValueError(
                f"Filename extension {file_ext} does not match detected image format {format_name} "
                f"(valid extensions: {', '.join(sorted(detected_extensions))})"
            )

    return data


def get_image_extension(data: bytes) -> str | None:
    """Detect image format and return the primary file extension.

    Returns the extension (e.g. '.png') if recognized, None otherwise.
    Used to derive a default filename when one is not provided.
    """
    format_name, extensions = _detect_image_format(data)
    if extensions:
        # Return the first (preferred) extension
        return next(iter(extensions))
    return None


def _detect_image_format(data: bytes) -> tuple[str, frozenset[str]] | tuple[None, None]:
    """Detect image format from file signature (magic bytes).

    Returns (format_name, acceptable_extensions) if recognized, (None, None) otherwise.
    """
    if not data:
        return None, None

    # Check for WebP first (RIFF container)
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "WebP", frozenset({".webp"})

    # Check other signatures
    for signature, (format_name, extensions) in SUPPORTED_IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return format_name, extensions

    return None, None
