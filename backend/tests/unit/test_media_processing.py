"""Image verification and re-encoding (BL-1.08; POST-004, T-MED-01/02)."""

from __future__ import annotations

import hashlib
import io

import pytest
from PIL import ExifTags, Image

from app.modules.media.processing import RejectedMediaError, process_image, sniff, verify

pytestmark = pytest.mark.req("POST-004")


def jpeg_with_gps(width: int = 2000, height: int = 1000, orientation: int = 6) -> bytes:
    image = Image.new("RGB", (width, height), (200, 60, 40))
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = orientation
    exif[ExifTags.Base.Make] = "TestCam"
    exif[ExifTags.IFD.GPSInfo] = {
        ExifTags.GPS.GPSLatitudeRef: "N",
        ExifTags.GPS.GPSLatitude: (38.0, 42.0, 0.0),
        ExifTags.GPS.GPSLongitudeRef: "W",
        ExifTags.GPS.GPSLongitude: (9.0, 8.0, 0.0),
    }
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif.tobytes(), quality=90)
    return buffer.getvalue()


def test_the_fixture_really_carries_gps() -> None:
    with Image.open(io.BytesIO(jpeg_with_gps())) as image:
        assert image.getexif().get_ifd(ExifTags.IFD.GPSInfo)


def test_variants_have_no_metadata_and_keep_orientation() -> None:
    processed = process_image(jpeg_with_gps())
    # Orientation 6 = rotate 90°: the displayed image is portrait.
    assert (processed.width, processed.height) == (1000, 2000)
    assert [(v.width, v.height) for v in processed.variants] == [
        (1000, 2000),
        (800, 1600),
        (320, 640),
    ]
    for variant in processed.variants:
        assert sniff(variant.data) == "image/webp"
        with Image.open(io.BytesIO(variant.data)) as image:
            assert not image.getexif()
            assert "exif" not in image.info
            assert "icc_profile" not in image.info


def test_small_images_are_not_upscaled() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (200, 100), (0, 0, 0, 0)).save(buffer, "PNG")
    processed = process_image(buffer.getvalue())
    assert [(v.width, v.height) for v in processed.variants] == [(200, 100)]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic", "image/heic"),
        (b"\x00\x00\x00\x18ftypisom", "video/mp4"),
        (b"MZ\x90\x00", None),
    ],
)
def test_magic_bytes(data: bytes, expected: str | None) -> None:
    assert sniff(data) == expected


@pytest.mark.security
def test_declared_values_are_checked() -> None:
    data = jpeg_with_gps(64, 64)
    digest = hashlib.sha256(data).hexdigest()
    verify(data, declared_type="image/jpeg", declared_bytes=len(data), declared_sha256=digest)
    cases = [
        ({"declared_type": "image/png", "declared_bytes": len(data)}, "type_mismatch"),
        ({"declared_type": "image/jpeg", "declared_bytes": len(data) + 1}, "hash_mismatch"),
        ({"declared_type": "image/jpeg", "declared_bytes": len(data) - 1}, "too_large"),
    ]
    for kwargs, reason in cases:
        with pytest.raises(RejectedMediaError) as caught:
            verify(data, declared_sha256=digest, **kwargs)  # type: ignore[arg-type]
        assert caught.value.reason == reason


@pytest.mark.security
def test_polyglots_and_garbage_fail_processing() -> None:
    with pytest.raises(RejectedMediaError) as caught:
        process_image(b"\xff\xd8\xff" + b"<script>alert(1)</script>" * 10)
    assert caught.value.reason == "processing_failed"


@pytest.mark.security
def test_decompression_bombs_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.media.processing.MAX_PIXELS", 10_000)
    buffer = io.BytesIO()
    Image.new("L", (400, 400)).save(buffer, "PNG")  # 160k px > 2x the patched limit
    with pytest.raises(RejectedMediaError) as caught:
        process_image(buffer.getvalue())
    assert caught.value.reason == "too_large"
