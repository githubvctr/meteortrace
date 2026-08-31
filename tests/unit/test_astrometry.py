"""Unit tests for `meteortrace.astrometry`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS, Sip

from meteortrace.astrometry import (
    DimensionResolutionError,
    NonCelestialWcsError,
    is_within_bounds,
    load_wcs,
    pixel_to_sky,
    roundtrip_pixel_error,
    sky_to_pixel,
)
from meteortrace.contracts import CelestialCoordinate
from meteortrace.pixels import PixelCoordinate, PixelSpace


def _base_header(
    crval1: float = 10.0,
    width: int = 100,
    height: int = 60,
    include_image_dims: bool = True,
) -> fits.Header:
    header = fits.Header()
    header["WCSAXES"] = 2
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRPIX1"] = 50.0
    header["CRPIX2"] = 30.0
    header["CRVAL1"] = crval1
    header["CRVAL2"] = 20.0
    header["CD1_1"] = -0.001
    header["CD1_2"] = 0.0
    header["CD2_1"] = 0.0
    header["CD2_2"] = 0.001
    if include_image_dims:
        header["IMAGEW"] = width
        header["IMAGEH"] = height
    return header


def _write_fits(
    tmp_path: Path,
    header: fits.Header,
    name: str = "test.fits",
    pixel_data_shape: tuple[int, int] | None = None,
) -> Path:
    path = tmp_path / name
    data = np.zeros(pixel_data_shape, dtype=np.uint8) if pixel_data_shape else None
    hdu = fits.PrimaryHDU(data=data)
    for key, value in header.items():
        if key in ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND"):
            continue
        hdu.header[key] = value
    hdu.writeto(path)
    return path


def test_synthetic_tan_wcs_known_pixel_sky_position(tmp_path: Path) -> None:
    path = _write_fits(tmp_path, _base_header())
    wcs, summary = load_wcs(path)

    assert (summary.width, summary.height) == (100, 60)
    assert summary.ctype == ("RA---TAN", "DEC--TAN")

    # The reference pixel (CRPIX - 1 in zero-based indexing) must map
    # exactly onto (CRVAL1, CRVAL2) for a pure TAN projection.
    point = PixelCoordinate(x=49.0, y=29.0, space=PixelSpace.WCS_SOLVED)
    sky = pixel_to_sky(wcs, point)
    assert sky.ra_deg == pytest.approx(10.0, abs=1e-9)
    assert sky.dec_deg == pytest.approx(20.0, abs=1e-9)


def test_pixel_sky_pixel_round_trip(tmp_path: Path) -> None:
    path = _write_fits(tmp_path, _base_header())
    wcs, _ = load_wcs(path)

    point = PixelCoordinate(x=12.3, y=44.7, space=PixelSpace.WCS_SOLVED)
    sky = pixel_to_sky(wcs, point)
    back = sky_to_pixel(wcs, sky)

    assert back.x == pytest.approx(point.x, abs=1e-6)
    assert back.y == pytest.approx(point.y, abs=1e-6)
    assert roundtrip_pixel_error(wcs, point) < 1e-6


def test_ra_wraparound_stays_within_0_360(tmp_path: Path) -> None:
    # CRVAL1 close to 0 deg; a pixel far to the right crosses the 0/360
    # boundary and must be represented as a wrapped positive value, not a
    # negative one.
    path = _write_fits(tmp_path, _base_header(crval1=0.05))
    wcs, _ = load_wcs(path)

    point = PixelCoordinate(x=2000.0, y=29.0, space=PixelSpace.WCS_SOLVED)
    sky = pixel_to_sky(wcs, point)
    assert 0.0 <= sky.ra_deg < 360.0
    assert sky.ra_deg == pytest.approx(357.97, abs=0.1)


def test_bounds_check_is_independent_of_transform_validity(tmp_path: Path) -> None:
    path = _write_fits(tmp_path, _base_header(width=100, height=60))
    wcs, summary = load_wcs(path)

    inside = PixelCoordinate(x=0.0, y=0.0, space=PixelSpace.WCS_SOLVED)
    outside = PixelCoordinate(x=-10.0, y=0.0, space=PixelSpace.WCS_SOLVED)

    assert is_within_bounds(inside, summary.width, summary.height) is True
    assert is_within_bounds(outside, summary.width, summary.height) is False
    # The coordinate transform itself must still succeed for out-of-bounds
    # pixels: boundedness is a separate concern from transformability.
    pixel_to_sky(wcs, outside)


def test_non_celestial_wcs_raises(tmp_path: Path) -> None:
    header = fits.Header()
    header["WCSAXES"] = 2
    header["CTYPE1"] = "LINEAR"
    header["CTYPE2"] = "LINEAR"
    header["CRPIX1"] = 1.0
    header["CRPIX2"] = 1.0
    header["CRVAL1"] = 0.0
    header["CRVAL2"] = 0.0
    header["CD1_1"] = 1.0
    header["CD2_2"] = 1.0
    header["IMAGEW"] = 10
    header["IMAGEH"] = 10
    path = _write_fits(tmp_path, header)
    wcs, _ = load_wcs(path)

    point = PixelCoordinate(x=0.0, y=0.0, space=PixelSpace.WCS_SOLVED)
    with pytest.raises(NonCelestialWcsError):
        pixel_to_sky(wcs, point)
    with pytest.raises(NonCelestialWcsError):
        sky_to_pixel(wcs, CelestialCoordinate(ra_deg=0.0, dec_deg=0.0))


def test_pixel_to_sky_rejects_wrong_pixel_space(tmp_path: Path) -> None:
    path = _write_fits(tmp_path, _base_header())
    wcs, _ = load_wcs(path)
    wrong_space_point = PixelCoordinate(x=0.0, y=0.0, space=PixelSpace.ENCODED)
    with pytest.raises(ValueError):
        pixel_to_sky(wcs, wrong_space_point)


def test_dimension_sources_agree(tmp_path: Path) -> None:
    header = _base_header(width=100, height=60)
    path = _write_fits(tmp_path, header, pixel_data_shape=(60, 100))
    _, summary = load_wcs(path)
    assert (summary.width, summary.height) == (100, 60)
    assert set(summary.dimension_sources) == {
        "IMAGEW_IMAGEH",
        "NAXIS1_NAXIS2",
        "wcs_pixel_shape",
    }


def test_dimension_sources_disagreement_raises(tmp_path: Path) -> None:
    header = _base_header(width=100, height=60)
    # Data shape (rows=height, cols=width) deliberately disagrees with IMAGEH.
    path = _write_fits(tmp_path, header, pixel_data_shape=(61, 100))
    with pytest.raises(DimensionResolutionError):
        load_wcs(path)


def test_no_dimension_source_raises(tmp_path: Path) -> None:
    header = _base_header(include_image_dims=False)
    path = _write_fits(tmp_path, header)
    with pytest.raises(DimensionResolutionError):
        load_wcs(path)


def test_sip_distortion_round_trip(tmp_path: Path) -> None:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
    w.wcs.crpix = [50.0, 30.0]
    w.wcs.crval = [10.0, 20.0]
    w.wcs.cd = [[-0.001, 0.0], [0.0, 0.001]]
    a = np.zeros((3, 3))
    a[2, 0] = 1e-6
    b = np.zeros((3, 3))
    b[0, 2] = 1e-6
    w.sip = Sip(a, b, None, None, w.wcs.crpix)

    header = w.to_header(relax=True)
    header["IMAGEW"] = 100
    header["IMAGEH"] = 60
    path = _write_fits(tmp_path, header)

    wcs, summary = load_wcs(path)
    assert summary.has_sip is True
    assert summary.sip_orders == (2, 2)

    point = PixelCoordinate(x=40.0, y=35.0, space=PixelSpace.WCS_SOLVED)
    sky = pixel_to_sky(wcs, point)
    back = sky_to_pixel(wcs, sky)
    assert back.x == pytest.approx(point.x, abs=1e-6)
    assert back.y == pytest.approx(point.y, abs=1e-6)


def test_width_height_and_xy_are_not_confused(tmp_path: Path) -> None:
    # A markedly non-square grid catches any accidental (row, col) vs
    # (x, y) transposition in dimension resolution or bounds checking.
    path = _write_fits(tmp_path, _base_header(width=200, height=20))
    _, summary = load_wcs(path)
    assert summary.width == 200
    assert summary.height == 20

    just_inside_wide_axis = PixelCoordinate(x=199.0, y=0.0, space=PixelSpace.WCS_SOLVED)
    just_outside_narrow_axis = PixelCoordinate(
        x=0.0, y=25.0, space=PixelSpace.WCS_SOLVED
    )
    assert (
        is_within_bounds(just_inside_wide_axis, summary.width, summary.height) is True
    )
    assert (
        is_within_bounds(just_outside_narrow_axis, summary.width, summary.height)
        is False
    )
