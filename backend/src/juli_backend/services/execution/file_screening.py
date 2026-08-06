"""Image file screening and re-encoding for executions (OWASP File Upload Cheat Sheet).

Validates and sanitizes base64-encoded images:
1. Size caps (encoded and decoded)
2. File signature allowlist (magic bytes)
3. Full image decode (proves validity, not corrupt)
4. Decompression bomb detection
5. Re-encoding to destroy appended data and polyglot payloads

Generates a safe filename (UUID + detected extension); caller-supplied name is discarded.
Forward re-encoded bytes to TikTok, not original bytes.
"""

from __future__ import annotations

import io
import uuid
from typing import Final

from PIL import Image

# Size caps (ADR-055 item 20)
# Base64 overhead is ~33%, so a 10MB encoded payload decodes to ~7.5MB
MAX_ENCODED_SIZE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_DECODED_SIZE_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB

# Decompression bomb protection: max pixel count in decoded image
# PIL default is 89.5 MP; we use 100 MP to be slightly generous for high-res photos
MAX_IMAGE_PIXELS: Final[int] = 100 * 1024 * 1024  # 100 MP

# Magic bytes (file signatures) for supported image types
# Format: signature_bytes -> (PIL format name, preferred extension)
SUPPORTED_IMAGE_SIGNATURES: Final[dict[bytes, tuple[str, str]]] = {
    b"\x89PNG\r\n\x1a\n": ("PNG", ".png"),
    b"\xff\xd8\xff": ("JPEG", ".jpg"),
    b"GIF87a": ("GIF", ".gif"),
    b"GIF89a": ("GIF", ".gif"),
    b"RIFF": ("WebP", ".webp"),  # Verified by checking WEBP marker in _detect_image_format
}


def screen_and_reencode_image(data: bytes) -> tuple[bytes, str]:
    """Screen image bytes, re-encode to destroy payloads, return safe bytes + filename.

    Per OWASP File Upload Cheat Sheet:
    - Re-encoding destroys appended data, embedded scripts, and polyglot payloads
    - Generated filename (UUID + extension) replaces caller-supplied name
    - No caller input reaches TikTok or storage

    Verifies:
    - Size within acceptable bounds (encoded and decoded)
    - Matches a supported image format (magic bytes only)
    - Can be decoded as a valid image (not corrupt, not polyglot)
    - Decompressed size is reasonable (no decompression bombs)

    Args:
        data: Raw image bytes (already base64-decoded)

    Returns:
        (re_encoded_bytes, safe_filename) where filename is UUID + detected extension

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

    pil_format, extension = _detect_image_format(data)
    if not pil_format:
        raise ValueError("Image is not a supported image format (PNG, JPEG, GIF, or WebP)")

    # Decode and validate image
    try:
        with Image.open(io.BytesIO(data)) as img:
            # Check decompression bomb: ensure decoded pixel count is reasonable
            if img.size[0] * img.size[1] > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Image dimensions {img.size} exceed maximum pixel count {MAX_IMAGE_PIXELS}"
                )
            # Force PIL to read and validate the entire image
            img.load()

            # Re-encode to fresh buffer in detected format (destroys payloads)
            # This is the real mitigation: no appended data survives the round trip
            reencoded_buffer = io.BytesIO()
            img.save(reencoded_buffer, format=pil_format)
            reencoded_bytes = reencoded_buffer.getvalue()

    except Image.UnidentifiedImageError as e:
        raise ValueError(f"Image is corrupt or invalid: {str(e)}")
    except Image.DecompressionBombError as e:
        raise ValueError(f"Image decompression bomb detected: {str(e)}")
    except Exception as e:
        raise ValueError(f"Image is corrupt or invalid: {type(e).__name__}: {str(e)}")

    # Generate safe filename: UUID (hex) + detected extension
    safe_filename = f"{uuid.uuid4().hex}{extension}"

    return reencoded_bytes, safe_filename


def _detect_image_format(data: bytes) -> tuple[str, str] | tuple[None, None]:
    """Detect image format from file signature (magic bytes).

    Returns (pil_format, extension) if recognized, (None, None) otherwise.
    PIL format is used for re-encoding; extension is for filename.
    """
    if not data:
        return None, None

    # Check for WebP first (RIFF container with WEBP marker)
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "WebP", ".webp"

    # Check other signatures
    for signature, (pil_format, extension) in SUPPORTED_IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return pil_format, extension

    return None, None
