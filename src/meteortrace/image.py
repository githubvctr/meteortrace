"""Read-only image metadata extraction, distinguishing encoded and display pixel grids.

HEIC/HEIF decoding is enabled via `pillow-heif`, registered once at import
time so that `PIL.Image.open` can read `.heic`/`.heif` files transparently.
No source file is ever written to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pillow_heif
from PIL import Image

from meteortrace.pixels import OrientationTransform

pillow_heif.register_heif_opener()

# EXIF tag IDs used below (see the EXIF 2.3 specification).
_TAG_ORIENTATION = 274
_TAG_MAKE = 271
_TAG_MODEL = 272
_IFD_EXIF = 0x8769
_IFD_GPS = 0x8825
_TAG_LENS_MODEL = 42036
_TAG_FOCAL_LENGTH = 37386
_TAG_FOCAL_LENGTH_35MM = 41989
_TAG_DATETIME_ORIGINAL = 36867
_TAG_OFFSET_TIME_ORIGINAL = 36881

# HEIC decoding limitation: whether pillow-heif applies EXIF-orientation
# rotation itself before `Image.size` is observed cannot be determined
# from files whose orientation tag is 1 (no rotation required either
# way). This package therefore treats `Image.size` as the `ENCODED` grid
# consistent with the reported orientation tag, and always applies the
# orientation transform explicitly rather than relying on implicit
# decoder correction. See docs/input_provenance_and_wcs.md.
HEIC_ORIENTATION_LIMITATION = (
    "Decoder-applied orientation could not be empirically verified from "
    "files with EXIF orientation = 1; encoded dimensions are trusted "
    "as reported and orientation is always applied explicitly."
)


def _parse_exif_datetime(value: str | None) -> str | None:
    """Parse an EXIF `"YYYY:MM:DD HH:MM:SS"` datetime into a naive ISO string."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class ImageMetadata:
    """Non-sensitive metadata for one image file.

    `capture_datetime_recorded` is the EXIF datetime exactly as recorded,
    with no timezone applied: it is offset-naive unless
    `capture_utc_offset` is also present. GPS presence is recorded as a
    boolean only; coordinate values are never captured here.
    """

    role: str
    file_format: str
    color_mode: str
    encoded_width: int
    encoded_height: int
    display_width: int
    display_height: int
    exif_orientation: int
    camera_make: str | None
    camera_model: str | None
    lens_model: str | None
    focal_length_mm: float | None
    focal_length_35mm_equiv: int | None
    capture_datetime_recorded: str | None
    capture_utc_offset: str | None
    has_gps: bool

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "file_format": self.file_format,
            "color_mode": self.color_mode,
            "encoded_width": self.encoded_width,
            "encoded_height": self.encoded_height,
            "display_width": self.display_width,
            "display_height": self.display_height,
            "exif_orientation": self.exif_orientation,
            "camera_make": self.camera_make,
            "camera_model": self.camera_model,
            "lens_model": self.lens_model,
            "focal_length_mm": self.focal_length_mm,
            "focal_length_35mm_equiv": self.focal_length_35mm_equiv,
            "capture_datetime_recorded": self.capture_datetime_recorded,
            "capture_utc_offset": self.capture_utc_offset,
            "has_gps": self.has_gps,
        }


def read_image_metadata(path: Path, role: str) -> ImageMetadata:
    """Read non-sensitive metadata from an image file, without modifying it.

    Raises
    ------
    FileNotFoundError
        If `path` does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path.name!r}")

    with Image.open(path) as image:
        encoded_width, encoded_height = image.size
        file_format = image.format or "UNKNOWN"
        color_mode = image.mode
        exif = image.getexif()

        orientation = exif.get(_TAG_ORIENTATION, 1)
        if orientation not in range(1, 9):
            orientation = 1

        camera_make = exif.get(_TAG_MAKE)
        camera_model = exif.get(_TAG_MODEL)

        exif_ifd = {}
        try:
            exif_ifd = dict(exif.get_ifd(_IFD_EXIF))
        except (KeyError, AttributeError, ValueError):
            exif_ifd = {}

        lens_model = exif_ifd.get(_TAG_LENS_MODEL)
        focal_length = exif_ifd.get(_TAG_FOCAL_LENGTH)
        focal_length_35mm = exif_ifd.get(_TAG_FOCAL_LENGTH_35MM)
        capture_datetime_recorded = _parse_exif_datetime(
            exif_ifd.get(_TAG_DATETIME_ORIGINAL)
        )
        capture_utc_offset = exif_ifd.get(_TAG_OFFSET_TIME_ORIGINAL) or None

        has_gps = False
        try:
            has_gps = bool(exif.get_ifd(_IFD_GPS))
        except (KeyError, AttributeError, ValueError):
            has_gps = False

    transform = OrientationTransform(
        orientation=orientation,
        encoded_width=encoded_width,
        encoded_height=encoded_height,
    )

    return ImageMetadata(
        role=role,
        file_format=file_format,
        color_mode=color_mode,
        encoded_width=encoded_width,
        encoded_height=encoded_height,
        display_width=transform.display_width,
        display_height=transform.display_height,
        exif_orientation=orientation,
        camera_make=str(camera_make) if camera_make is not None else None,
        camera_model=str(camera_model) if camera_model is not None else None,
        lens_model=str(lens_model) if lens_model is not None else None,
        focal_length_mm=float(focal_length) if focal_length is not None else None,
        focal_length_35mm_equiv=(
            int(focal_length_35mm) if focal_length_35mm is not None else None
        ),
        capture_datetime_recorded=capture_datetime_recorded,
        capture_utc_offset=capture_utc_offset,
        has_gps=has_gps,
    )


def capture_time_difference_seconds(a: ImageMetadata, b: ImageMetadata) -> float | None:
    """Signed time difference `b - a`, in seconds.

    Returns `None` unless both images carry a recorded capture datetime
    *and* an explicit UTC offset: this package never invents a timezone
    to make a comparison possible.
    """
    if not (
        a.capture_datetime_recorded
        and b.capture_datetime_recorded
        and a.capture_utc_offset
        and b.capture_utc_offset
    ):
        return None
    dt_a = datetime.fromisoformat(a.capture_datetime_recorded + a.capture_utc_offset)
    dt_b = datetime.fromisoformat(b.capture_datetime_recorded + b.capture_utc_offset)
    return (dt_b - dt_a).total_seconds()
