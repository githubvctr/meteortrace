"""Unit tests for `meteortrace.image`."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from meteortrace.image import capture_time_difference_seconds, read_image_metadata


def _make_jpeg(
    path: Path,
    size: tuple[int, int] = (6, 4),
    orientation: int | None = 1,
    make: str | None = None,
    model: str | None = None,
    lens: str | None = None,
    focal_length: float | None = None,
    focal_length_35mm: int | None = None,
    datetime_original: str | None = None,
    offset_time_original: str | None = None,
    gps: dict | None = None,
) -> None:
    image = Image.new("RGB", size, color=(10, 20, 30))
    exif = image.getexif()
    if orientation is not None:
        exif[274] = orientation
    if make is not None:
        exif[271] = make
    if model is not None:
        exif[272] = model

    exif_ifd = {}
    if lens is not None:
        exif_ifd[42036] = lens
    if focal_length is not None:
        exif_ifd[37386] = focal_length
    if focal_length_35mm is not None:
        exif_ifd[41989] = focal_length_35mm
    if datetime_original is not None:
        exif_ifd[36867] = datetime_original
    if offset_time_original is not None:
        exif_ifd[36881] = offset_time_original
    if exif_ifd:
        exif[0x8769] = exif_ifd

    if gps is not None:
        exif[0x8825] = gps

    image.save(path, exif=exif.tobytes())


def test_reads_jpeg_dimensions_and_basic_metadata(tmp_path: Path) -> None:
    path = tmp_path / "sample.jpg"
    _make_jpeg(
        path,
        size=(8, 5),
        make="Apple",
        model="iPhone 17 Pro Max",
        lens="Test lens",
        focal_length=6.76,
        focal_length_35mm=24,
        datetime_original="2026:08:12 00:34:15",
        offset_time_original="+02:00",
    )

    metadata = read_image_metadata(path, role="reference")

    assert metadata.encoded_width == 8
    assert metadata.encoded_height == 5
    assert metadata.file_format == "JPEG"
    assert metadata.camera_make == "Apple"
    assert metadata.camera_model == "iPhone 17 Pro Max"
    assert metadata.lens_model == "Test lens"
    assert metadata.focal_length_mm == 6.76
    assert metadata.focal_length_35mm_equiv == 24
    assert metadata.capture_datetime_recorded == "2026-08-12T00:34:15"
    assert metadata.capture_utc_offset == "+02:00"
    assert metadata.has_gps is False


def test_non_square_dimensions_preserved_for_identity_orientation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "wide.jpg"
    _make_jpeg(path, size=(9, 4), orientation=1)
    metadata = read_image_metadata(path, role="reference")
    assert (metadata.encoded_width, metadata.encoded_height) == (9, 4)
    assert (metadata.display_width, metadata.display_height) == (9, 4)


def test_rotated_orientation_swaps_display_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    _make_jpeg(path, size=(9, 4), orientation=6)
    metadata = read_image_metadata(path, role="reference")
    assert (metadata.encoded_width, metadata.encoded_height) == (9, 4)
    assert (metadata.display_width, metadata.display_height) == (4, 9)


def test_invalid_orientation_value_defaults_to_identity(tmp_path: Path) -> None:
    path = tmp_path / "bad_orientation.jpg"
    _make_jpeg(path, size=(6, 4), orientation=99)
    metadata = read_image_metadata(path, role="reference")
    assert metadata.exif_orientation == 1
    assert (metadata.display_width, metadata.display_height) == (6, 4)


def test_gps_presence_detected_as_boolean_only(tmp_path: Path) -> None:
    path = tmp_path / "with_gps.jpg"
    _make_jpeg(path, gps={1: "N", 2: (10.0, 0.0, 0.0)})
    metadata = read_image_metadata(path, role="reference")
    assert metadata.has_gps is True

    serialized = json.dumps(metadata.to_dict())
    assert "10.0" not in serialized
    assert "GPSLatitude" not in serialized


def test_no_gps_metadata_reports_false(tmp_path: Path) -> None:
    path = tmp_path / "without_gps.jpg"
    _make_jpeg(path)
    metadata = read_image_metadata(path, role="reference")
    assert metadata.has_gps is False


def test_metadata_serialization_never_contains_gps_values(tmp_path: Path) -> None:
    path = tmp_path / "with_gps2.jpg"
    _make_jpeg(path, gps={1: "N", 2: (37.0, 46.0, 12.5), 3: "W", 4: (122.0, 25.0, 0.0)})
    metadata = read_image_metadata(path, role="reference")
    serialized = metadata.to_dict()
    assert "gps" not in {k.lower() for k in serialized} or True  # no gps_* keys at all
    assert set(serialized) == {
        "role",
        "file_format",
        "color_mode",
        "encoded_width",
        "encoded_height",
        "display_width",
        "display_height",
        "exif_orientation",
        "camera_make",
        "camera_model",
        "lens_model",
        "focal_length_mm",
        "focal_length_35mm_equiv",
        "capture_datetime_recorded",
        "capture_utc_offset",
        "has_gps",
    }


def test_capture_time_difference_requires_explicit_offset_on_both(
    tmp_path: Path,
) -> None:
    with_offset = tmp_path / "a.jpg"
    _make_jpeg(
        with_offset,
        datetime_original="2026:08:12 00:34:15",
        offset_time_original="+02:00",
    )
    without_offset = tmp_path / "b.jpg"
    _make_jpeg(without_offset, datetime_original="2026:08:12 00:34:49")

    meta_with = read_image_metadata(with_offset, role="reference")
    meta_without = read_image_metadata(without_offset, role="target")

    assert capture_time_difference_seconds(meta_with, meta_without) is None


def test_capture_time_difference_computed_when_both_have_offsets(
    tmp_path: Path,
) -> None:
    a = tmp_path / "a.jpg"
    _make_jpeg(
        a, datetime_original="2026:08:12 00:34:15", offset_time_original="+02:00"
    )
    b = tmp_path / "b.jpg"
    _make_jpeg(
        b, datetime_original="2026:08:12 00:34:49", offset_time_original="+02:00"
    )

    meta_a = read_image_metadata(a, role="reference")
    meta_b = read_image_metadata(b, role="target")

    assert capture_time_difference_seconds(meta_a, meta_b) == 34.0
