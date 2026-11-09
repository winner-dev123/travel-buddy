"""Image checks and re-encoding (pure). POST-004, T-MED-01/02.

Every image is decoded and re-encoded, which drops EXIF/GPS and any polyglot payload; orientation
is applied first so stripping the EXIF orientation tag doesn't rotate photos. Decompression bombs
are refused by Pillow's pixel limit.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 50_000_000
VARIANT_WIDTHS = (1600, 800, 320)
WEBP_QUALITY = 82


class RejectedMediaError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def sniff(data: bytes) -> str | None:
    """MIME type from magic bytes, or ``None`` when unrecognized."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "image/heic"
        if brand == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    return None


def verify(data: bytes, *, declared_type: str, declared_bytes: int, declared_sha256: str) -> None:
    if len(data) > declared_bytes:
        raise RejectedMediaError("too_large")
    if len(data) != declared_bytes or hashlib.sha256(data).hexdigest() != declared_sha256:
        raise RejectedMediaError("hash_mismatch")
    if sniff(data) != declared_type:
        raise RejectedMediaError("type_mismatch")


@dataclass(frozen=True, slots=True)
class Variant:
    width: int
    height: int
    data: bytes


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    width: int
    height: int
    variants: list[Variant]  # largest first


def process_image(data: bytes) -> ProcessedImage:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
            if image.mode not in ("RGB", "RGBA"):
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
            width, height = image.size
            variants: list[Variant] = []
            for target in sorted({min(w, width) for w in VARIANT_WIDTHS}, reverse=True):
                scaled_height = max(1, round(height * target / width))
                resized = (
                    image
                    if target == width
                    else image.resize((target, scaled_height), Image.Resampling.LANCZOS)
                )
                buffer = io.BytesIO()
                # No exif/icc arguments: the output carries pixels only.
                resized.save(buffer, "WEBP", quality=WEBP_QUALITY, method=4)
                variants.append(Variant(target, scaled_height, buffer.getvalue()))
    except Image.DecompressionBombError as exc:
        raise RejectedMediaError("too_large") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise RejectedMediaError("processing_failed") from exc
    return ProcessedImage(width=width, height=height, variants=variants)
