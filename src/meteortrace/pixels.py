"""Pixel-space contracts and explicit EXIF-orientation transforms.

Three distinct pixel spaces are used across this package, and a pixel
coordinate must always carry an explicit identity for one of them so that
functions cannot silently accept coordinates from the wrong space:

- ``ENCODED``: the pixel grid exactly as stored/decoded from the image
  file, before any EXIF-orientation correction is applied.
- ``DISPLAY``: the orientation-normalized grid a viewer would show, after
  applying the EXIF orientation transform.
- ``WCS_SOLVED``: the pixel grid that the ingested WCS solution was
  computed against. This is not assumed to equal either of the above; it
  must be established separately (see ``meteortrace.astrometry``).

Convention (shared with the rest of the package): pixel coordinates are
zero-based, ``(0, 0)`` is the centre of the upper-left pixel, ``x``
increases right, ``y`` increases down, array shapes are ``(height,
width)``, and pixel points are ordered ``(x, y)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class PixelSpace(Enum):
    """Identity of the pixel grid a `PixelCoordinate` belongs to."""

    ENCODED = "encoded"
    DISPLAY = "display"
    WCS_SOLVED = "wcs_solved"


@dataclass(frozen=True)
class PixelCoordinate:
    """A pixel coordinate tagged with the pixel space it belongs to.

    Parameters
    ----------
    x : float
        Horizontal position; increases to the right. Zero-based, with the
        centre of the leftmost pixel column at ``x = 0``.
    y : float
        Vertical position; increases downward. Zero-based, with the
        centre of the topmost pixel row at ``y = 0``.
    space : PixelSpace
        Which pixel grid this coordinate is expressed in.
    """

    x: float
    y: float
    space: PixelSpace

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError(f"x and y must be finite, got x={self.x}, y={self.y}.")


def require_space(point: PixelCoordinate, expected: PixelSpace) -> None:
    """Raise `ValueError` unless `point` belongs to the `expected` pixel space."""
    if point.space is not expected:
        raise ValueError(
            f"Expected a pixel coordinate in space {expected.value!r}, "
            f"got {point.space.value!r}."
        )


# Forward pixel-mapping formulas for each of the eight EXIF orientation
# values, applied to zero-based, pixel-centre coordinates. Each maps a
# point (x, y) in a W x H source grid to a point in the transformed grid,
# returning the transformed grid's (width, height) alongside it. Derived
# from the standard EXIF orientation definitions (e.g. as documented by
# ExifTool): mirror/rotate operations composed in the stated order.
def _identity(x: float, y: float, w: int, h: int) -> tuple[float, float, int, int]:
    return x, y, w, h


def _mirror_horizontal(
    x: float, y: float, w: int, h: int
) -> tuple[float, float, int, int]:
    return (w - 1) - x, y, w, h


def _rotate_180(x: float, y: float, w: int, h: int) -> tuple[float, float, int, int]:
    return (w - 1) - x, (h - 1) - y, w, h


def _mirror_vertical(
    x: float, y: float, w: int, h: int
) -> tuple[float, float, int, int]:
    return x, (h - 1) - y, w, h


def _transpose(x: float, y: float, w: int, h: int) -> tuple[float, float, int, int]:
    return y, x, h, w


def _rotate_90_cw(x: float, y: float, w: int, h: int) -> tuple[float, float, int, int]:
    return (h - 1) - y, x, h, w


def _transverse(x: float, y: float, w: int, h: int) -> tuple[float, float, int, int]:
    return (h - 1) - y, (w - 1) - x, h, w


def _rotate_270_cw(x: float, y: float, w: int, h: int) -> tuple[float, float, int, int]:
    return y, (w - 1) - x, h, w


_FORWARD_TRANSFORMS = {
    1: _identity,
    2: _mirror_horizontal,
    3: _rotate_180,
    4: _mirror_vertical,
    5: _transpose,
    6: _rotate_90_cw,
    7: _transverse,
    8: _rotate_270_cw,
}

# Orientation 6 (rotate 90 CW) and 8 (rotate 270 CW) are each other's
# inverse; the remaining transforms are involutions (self-inverse).
_INVERSE_ORIENTATION = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 8, 7: 7, 8: 6}


@dataclass(frozen=True)
class OrientationTransform:
    """The EXIF-orientation transform from an encoded grid to a display grid.

    Parameters
    ----------
    orientation : int
        EXIF orientation tag value, ``1``-``8``.
    encoded_width, encoded_height : int
        Dimensions of the source (`ENCODED`) pixel grid.

    Raises
    ------
    ValueError
        If `orientation` is not in ``1..8``, or if either dimension is not
        a positive integer.
    """

    orientation: int
    encoded_width: int
    encoded_height: int

    def __post_init__(self) -> None:
        if self.orientation not in _FORWARD_TRANSFORMS:
            raise ValueError(f"EXIF orientation must be 1-8, got {self.orientation}.")
        if self.encoded_width <= 0 or self.encoded_height <= 0:
            raise ValueError(
                "encoded_width and encoded_height must be positive, got "
                f"{self.encoded_width}x{self.encoded_height}."
            )

    @property
    def display_width(self) -> int:
        _, _, w, _ = _FORWARD_TRANSFORMS[self.orientation](
            0, 0, self.encoded_width, self.encoded_height
        )
        return w

    @property
    def display_height(self) -> int:
        _, _, _, h = _FORWARD_TRANSFORMS[self.orientation](
            0, 0, self.encoded_width, self.encoded_height
        )
        return h

    def to_display(self, point: PixelCoordinate) -> PixelCoordinate:
        """Map an `ENCODED`-space point to its `DISPLAY`-space equivalent."""
        require_space(point, PixelSpace.ENCODED)
        x, y, _, _ = _FORWARD_TRANSFORMS[self.orientation](
            point.x, point.y, self.encoded_width, self.encoded_height
        )
        return PixelCoordinate(x=x, y=y, space=PixelSpace.DISPLAY)

    def to_encoded(self, point: PixelCoordinate) -> PixelCoordinate:
        """Map a `DISPLAY`-space point back to its `ENCODED`-space equivalent."""
        require_space(point, PixelSpace.DISPLAY)
        inverse_orientation = _INVERSE_ORIENTATION[self.orientation]
        x, y, _, _ = _FORWARD_TRANSFORMS[inverse_orientation](
            point.x, point.y, self.display_width, self.display_height
        )
        return PixelCoordinate(x=x, y=y, space=PixelSpace.ENCODED)
