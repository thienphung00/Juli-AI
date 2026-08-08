"""Screening contract for the two execution upload paths.

Covers the regressions found reviewing the DPR wave (#776 / #774):

- the supporting-document path was screened with the image-only screener, so
  every PDF was rejected and the path was dead
- the encoded size cap was stated on the base64 string rather than derived from
  the decoded limit, making the server's effective limit ~7.5 MB while the
  upload control accepted 10 MB
- an animated GIF lost every frame but the first on re-encode
- a dimension rejection was relabelled as "corrupt or invalid" by the catch-all
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from juli_backend.services.execution import file_screening
from juli_backend.services.execution.file_screening import (
    MAX_DECODED_SIZE_BYTES,
    MAX_ENCODED_SIZE_BYTES,
    screen_and_reencode_image,
    screen_upload_file,
)


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _animated_gif_bytes() -> bytes:
    # Frames must differ visibly: identical P-mode frames collapse to one on
    # save, which would make this fixture silently single-frame.
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    images = [Image.new("RGB", (8, 8), colour).convert("P") for colour in colours]
    buffer = io.BytesIO()
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    # Minimal well-formed-enough PDF: the screener is an allowlist, not a parser.
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


class TestDocumentPath:
    def test_pdf_is_accepted_and_given_a_safe_filename(self) -> None:
        data = _pdf_bytes()

        screened, filename = screen_upload_file(data)

        assert screened == data, "a PDF is forwarded as supplied; it is not re-encoded"
        assert filename.endswith(".pdf")
        assert "/" not in filename and "\\" not in filename

    def test_pdf_is_rejected_by_the_image_only_screener(self) -> None:
        """The bug: routing documents through the image screener killed the path."""
        with pytest.raises(ValueError, match="not a supported image format"):
            screen_and_reencode_image(_pdf_bytes())

    def test_image_on_the_document_path_still_gets_re_encoded(self) -> None:
        screened, filename = screen_upload_file(_png_bytes())

        assert filename.endswith(".png")
        assert Image.open(io.BytesIO(screened)).format == "PNG"

    def test_unsupported_document_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a supported document format"):
            screen_upload_file(b"MZ\x90\x00 this is an executable")

    def test_empty_document_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            screen_upload_file(b"")


class TestSizeCaps:
    def test_encoded_cap_admits_a_file_at_the_decoded_limit(self) -> None:
        """A file the upload control accepts must not fail on encoding overhead."""
        encoded_len = len(base64.b64encode(b"\x00" * MAX_DECODED_SIZE_BYTES))

        assert encoded_len <= MAX_ENCODED_SIZE_BYTES

    def test_decoded_cap_matches_the_upload_control_default(self) -> None:
        # FileUploadField's maxSize default; the two are a single contract.
        assert MAX_DECODED_SIZE_BYTES == 10 * 1024 * 1024

    def test_oversized_document_is_rejected(self) -> None:
        oversized = b"%PDF-" + b"\x00" * MAX_DECODED_SIZE_BYTES

        with pytest.raises(ValueError, match="exceeds maximum decoded size"):
            screen_upload_file(oversized)


class TestImageReencoding:
    def test_animated_gif_keeps_every_frame(self) -> None:
        source = _animated_gif_bytes()
        with Image.open(io.BytesIO(source)) as original:
            assert getattr(original, "n_frames", 1) == 3, "fixture must be animated"

        screened, _ = screen_and_reencode_image(source)

        with Image.open(io.BytesIO(screened)) as result:
            assert getattr(result, "n_frames", 1) == 3

    def test_appended_payload_does_not_survive_re_encoding(self) -> None:
        poisoned = _png_bytes() + b"<?php system($_GET[0]); ?>"

        screened, _ = screen_and_reencode_image(poisoned)

        assert b"php" not in screened

    def test_dimension_rejection_keeps_its_own_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The catch-all must not relabel our own rejection as a corrupt file.

        The cap is lowered rather than building a >100 MP image: past PIL's own
        bomb threshold the open() call raises first and this branch is never
        reached, so a huge fixture would test the wrong thing.
        """
        monkeypatch.setattr(file_screening, "MAX_IMAGE_PIXELS", 4)

        with pytest.raises(ValueError, match="exceed maximum pixel count"):
            screen_and_reencode_image(_png_bytes(size=(8, 8)))
