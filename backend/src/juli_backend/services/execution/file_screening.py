"""File screening and re-encoding for executions (OWASP File Upload Cheat Sheet).

Two upload paths with deliberately different strength:

- **Product images** (`screen_and_reencode_image`) get the full treatment below,
  ending in a re-encode that destroys anything appended to the file.
- **Supporting documents** (`screen_upload_file`) accept an image *or* a PDF. A
  PDF cannot be re-encoded without a parser, so it gets the allowlist, the size
  cap and a generated filename, and its bytes are forwarded as supplied.

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

# Size caps (ADR-055 item 20).
#
# The cap that matters to a seller is the one on the file they picked, so the
# real limit is stated on the decoded bytes and the encoded limit is *derived*
# from it. Capping the base64 string at 10 MB instead would reject a 10 MB file
# the upload control accepted, because base64 inflates 3 bytes into 4 — the
# effective limit would have been ~7.5 MB, silently narrower than the client's.
# Keep MAX_DECODED_SIZE_BYTES in step with FileUploadField's `maxSize` default.
MAX_DECODED_SIZE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB of real bytes
# 4 chars per 3 bytes, plus slack for padding and any line breaks in transit.
MAX_ENCODED_SIZE_BYTES: Final[int] = 4 * ((MAX_DECODED_SIZE_BYTES + 2) // 3) + 1024

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

# Formats that can carry more than one frame; re-encoding these needs save_all.
ANIMATED_CAPABLE_FORMATS: Final[frozenset[str]] = frozenset({"GIF", "WebP"})

# Supporting documents are a different upload path from product images
# (`upload_product_file`, contract-collection.md §B-2a). They cannot be
# re-encoded the way an image can, so screening here is an allowlist plus the
# size cap plus a generated filename. That is materially weaker than the image
# path and is stated plainly rather than implied: a PDF's bytes are forwarded
# as supplied, so this is a boundary check, not sanitisation.
SUPPORTED_DOCUMENT_SIGNATURES: Final[dict[bytes, str]] = {
    b"%PDF-": ".pdf",
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
            # This is the real mitigation: no appended data survives the round trip.
            # Animated formats need every frame written, or the round trip
            # silently flattens the image to its first frame.
            reencoded_buffer = io.BytesIO()
            save_options: dict[str, object] = {}
            if pil_format in ANIMATED_CAPABLE_FORMATS and getattr(img, "n_frames", 1) > 1:
                save_options["save_all"] = True
            img.save(reencoded_buffer, format=pil_format, **save_options)
            reencoded_bytes = reencoded_buffer.getvalue()

    except ValueError:
        # Our own rejections (e.g. the dimension cap above) are already precise;
        # re-raise before the catch-all relabels them as "corrupt or invalid".
        raise
    except Image.UnidentifiedImageError as e:
        raise ValueError(f"Image is corrupt or invalid: {str(e)}")
    except Image.DecompressionBombError as e:
        raise ValueError(f"Image decompression bomb detected: {str(e)}")
    except Exception as e:
        raise ValueError(f"Image is corrupt or invalid: {type(e).__name__}: {str(e)}")

    # Generate safe filename: UUID (hex) + detected extension
    safe_filename = f"{uuid.uuid4().hex}{extension}"

    return reencoded_bytes, safe_filename


def screen_upload_file(data: bytes) -> tuple[bytes, str]:
    """Screen bytes headed for the supporting-document upload, return bytes + filename.

    The document path accepts what a seller can plausibly attach as supporting
    evidence: an image, or a PDF.

    - Images take the full image path — decoded, bomb-checked and re-encoded, so
      appended data and polyglot payloads do not survive.
    - PDFs cannot be re-encoded without a parser, so they get the allowlist, the
      size cap and a generated filename only. Their bytes are forwarded as
      supplied. This is weaker than the image path, deliberately and visibly.

    Screening a document with the image-only screener rejects every PDF, which
    is what shipped in #776 and broke this path outright.

    Args:
        data: Raw file bytes (already base64-decoded)

    Returns:
        (bytes_to_forward, safe_filename)

    Raises:
        ValueError: If the file fails any validation check
    """
    if not data:
        raise ValueError("File data is empty")

    if len(data) > MAX_DECODED_SIZE_BYTES:
        raise ValueError(
            f"File size {len(data)} bytes exceeds maximum decoded size "
            f"{MAX_DECODED_SIZE_BYTES} bytes"
        )

    pil_format, _ = _detect_image_format(data)
    if pil_format:
        return screen_and_reencode_image(data)

    for signature, extension in SUPPORTED_DOCUMENT_SIGNATURES.items():
        if data.startswith(signature):
            return data, f"{uuid.uuid4().hex}{extension}"

    raise ValueError(
        "File is not a supported document format (PDF) or image (PNG, JPEG, GIF, or WebP)"
    )


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
