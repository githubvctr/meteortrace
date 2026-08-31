"""Unit tests for `meteortrace.pixels`."""

from __future__ import annotations

import math

import pytest

from meteortrace.pixels import (
    OrientationTransform,
    PixelCoordinate,
    PixelSpace,
    require_space,
)

# (orientation, expected display (width, height) for a 5x3 encoded image)
_EXPECTED_DISPLAY_DIMS = {
    1: (5, 3),
    2: (5, 3),
    3: (5, 3),
    4: (5, 3),
    5: (3, 5),
    6: (3, 5),
    7: (3, 5),
    8: (3, 5),
}


@pytest.mark.parametrize("orientation", range(1, 9))
def test_all_eight_orientations_round_trip(orientation: int) -> None:
    transform = OrientationTransform(
        orientation=orientation, encoded_width=5, encoded_height=3
    )
    assert (
        transform.display_width,
        transform.display_height,
    ) == _EXPECTED_DISPLAY_DIMS[orientation]

    # Sample several points, including corners and an interior point.
    for x, y in [(0, 0), (4, 0), (0, 2), (4, 2), (2, 1)]:
        encoded = PixelCoordinate(x=x, y=y, space=PixelSpace.ENCODED)
        display = transform.to_display(encoded)
        assert display.space is PixelSpace.DISPLAY
        recovered = transform.to_encoded(display)
        assert recovered.space is PixelSpace.ENCODED
        assert recovered.x == pytest.approx(x)
        assert recovered.y == pytest.approx(y)


def test_identity_orientation_preserves_coordinates() -> None:
    transform = OrientationTransform(orientation=1, encoded_width=5, encoded_height=3)
    point = PixelCoordinate(x=2, y=1, space=PixelSpace.ENCODED)
    display = transform.to_display(point)
    assert (display.x, display.y) == (2, 1)


def test_rotate_90_cw_maps_top_left_corner_to_top_right() -> None:
    # Rotating a W=5,H=3 grid 90 degrees clockwise yields a 3x5 grid; the
    # source top-left pixel-centre must land at the new top-right corner.
    transform = OrientationTransform(orientation=6, encoded_width=5, encoded_height=3)
    top_left = PixelCoordinate(x=0, y=0, space=PixelSpace.ENCODED)
    display = transform.to_display(top_left)
    assert (display.x, display.y) == (transform.display_width - 1, 0)


def test_non_square_dimensions_are_respected() -> None:
    transform = OrientationTransform(orientation=8, encoded_width=10, encoded_height=4)
    assert transform.display_width == 4
    assert transform.display_height == 10


def test_invalid_orientation_value_raises() -> None:
    with pytest.raises(ValueError):
        OrientationTransform(orientation=0, encoded_width=5, encoded_height=3)
    with pytest.raises(ValueError):
        OrientationTransform(orientation=9, encoded_width=5, encoded_height=3)


def test_non_positive_dimensions_raise() -> None:
    with pytest.raises(ValueError):
        OrientationTransform(orientation=1, encoded_width=0, encoded_height=3)
    with pytest.raises(ValueError):
        OrientationTransform(orientation=1, encoded_width=5, encoded_height=-1)


def test_pixel_coordinate_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError):
        PixelCoordinate(x=math.nan, y=0.0, space=PixelSpace.ENCODED)
    with pytest.raises(ValueError):
        PixelCoordinate(x=0.0, y=math.inf, space=PixelSpace.ENCODED)


def test_require_space_rejects_wrong_space() -> None:
    point = PixelCoordinate(x=0.0, y=0.0, space=PixelSpace.ENCODED)
    require_space(point, PixelSpace.ENCODED)  # does not raise
    with pytest.raises(ValueError):
        require_space(point, PixelSpace.DISPLAY)


def test_transform_functions_reject_wrong_input_space() -> None:
    transform = OrientationTransform(orientation=1, encoded_width=5, encoded_height=3)
    display_point = PixelCoordinate(x=0.0, y=0.0, space=PixelSpace.DISPLAY)
    with pytest.raises(ValueError):
        transform.to_display(display_point)
    encoded_point = PixelCoordinate(x=0.0, y=0.0, space=PixelSpace.ENCODED)
    with pytest.raises(ValueError):
        transform.to_encoded(encoded_point)
