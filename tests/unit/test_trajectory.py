"""Unit tests for `meteortrace.trajectory`."""

from __future__ import annotations

from pathlib import Path

import pytest
from astropy.io import fits

from meteortrace.astrometry import load_wcs, resolve_celestial_frame
from meteortrace.contracts import CelestialCoordinate
from meteortrace.geometry import RadiantAlignment
from meteortrace.pixels import PixelCoordinate, PixelSpace
from meteortrace.selection import PixelClick
from meteortrace.trajectory import (
    ProvisionalRadiantModel,
    compute_mean_trajectory,
    pixel_to_icrs,
    radiant_to_icrs,
    run_monte_carlo_trajectory,
)
from meteortrace.uncertainty import (
    compute_endpoint_statistics,
    sample_endpoints_monte_carlo,
)


def _write_wcs(tmp_path: Path, width: int = 200, height: int = 300) -> Path:
    header = fits.Header()
    header["WCSAXES"] = 2
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRPIX1"] = width / 2
    header["CRPIX2"] = height / 2
    header["CRVAL1"] = 48.0
    header["CRVAL2"] = 58.0
    header["CD1_1"] = -0.001
    header["CD1_2"] = 0.0
    header["CD2_1"] = 0.0
    header["CD2_2"] = 0.001
    header["IMAGEW"] = width
    header["IMAGEH"] = height
    path = tmp_path / "wcs.fits"
    fits.PrimaryHDU(header=header).writeto(path)
    return path


def test_radiant_to_icrs_from_fk5_input() -> None:
    model = ProvisionalRadiantModel(name="Test", ra_deg=48.0, dec_deg=58.0, frame="fk5")
    radiant = radiant_to_icrs(model)
    # FK5(J2000) -> ICRS is a sub-arcsecond shift; the coordinate must
    # still be recognisably close to the input value.
    assert radiant.coordinate.ra_deg == pytest.approx(48.0, abs=1e-3)
    assert radiant.coordinate.dec_deg == pytest.approx(58.0, abs=1e-3)


def test_pixel_to_icrs_via_direct_wcs(tmp_path: Path) -> None:
    wcs_path = _write_wcs(tmp_path)
    wcs, summary = load_wcs(wcs_path)
    frame, _ = resolve_celestial_frame(wcs, summary)
    point = PixelCoordinate(x=99.0, y=149.0, space=PixelSpace.WCS_SOLVED)
    coordinate = pixel_to_icrs(wcs, frame, point)
    assert isinstance(coordinate, CelestialCoordinate)
    assert coordinate.ra_deg == pytest.approx(48.0, abs=0.1)
    assert coordinate.dec_deg == pytest.approx(58.0, abs=0.1)


def test_compute_mean_trajectory_end_to_end(tmp_path: Path) -> None:
    wcs_path = _write_wcs(tmp_path)
    wcs, summary = load_wcs(wcs_path)
    frame, _ = resolve_celestial_frame(wcs, summary)
    start = PixelCoordinate(x=80.0, y=100.0, space=PixelSpace.WCS_SOLVED)
    end = PixelCoordinate(x=120.0, y=200.0, space=PixelSpace.WCS_SOLVED)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )

    result = compute_mean_trajectory(wcs, frame, start, end, radiant_model)
    assert result.trail_length_deg > 0
    assert result.alignment in RadiantAlignment


def test_monte_carlo_trajectory_alignment_fractions_sum_to_one(tmp_path: Path) -> None:
    wcs_path = _write_wcs(tmp_path)
    wcs, summary = load_wcs(wcs_path)
    frame, _ = resolve_celestial_frame(wcs, summary)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )

    start_clicks = tuple(
        PixelClick(x=80.0 + i * 0.2, y=100.0 - i * 0.1) for i in range(5)
    )
    end_clicks = tuple(
        PixelClick(x=120.0 + i * 0.1, y=200.0 + i * 0.3) for i in range(5)
    )
    start_stats = compute_endpoint_statistics(start_clicks)
    end_stats = compute_endpoint_statistics(end_clicks)
    samples = sample_endpoints_monte_carlo(
        start_stats,
        end_stats,
        n_samples=500,
        seed=123,
        width=summary.width,
        height=summary.height,
    )

    summary_result = run_monte_carlo_trajectory(wcs, frame, samples, radiant_model)
    assert summary_result.n_samples_used <= summary_result.n_samples_requested
    total_fraction = sum(summary_result.alignment_fraction.values())
    assert total_fraction == pytest.approx(1.0, abs=1e-9)
    assert (
        summary_result.trail_length_deg_p2_5 <= summary_result.trail_length_deg_median
    )
    assert (
        summary_result.trail_length_deg_median <= summary_result.trail_length_deg_p97_5
    )


def test_known_synthetic_trajectory_matches_expected_geometry(tmp_path: Path) -> None:
    # A trail along the local pixel x-axis at the CRVAL/CRPIX reference
    # point should produce a small, well-defined trail length.
    wcs_path = _write_wcs(tmp_path, width=200, height=300)
    wcs, summary = load_wcs(wcs_path)
    frame, _ = resolve_celestial_frame(wcs, summary)
    start = PixelCoordinate(x=99.0, y=149.0, space=PixelSpace.WCS_SOLVED)
    end = PixelCoordinate(x=109.0, y=149.0, space=PixelSpace.WCS_SOLVED)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )

    result = compute_mean_trajectory(wcs, frame, start, end, radiant_model)
    # 10 pixels at ~0.00156 deg/pixel plate scale (from the CD matrix) is
    # a small but clearly nonzero, finite trail length.
    assert 0.0 < result.trail_length_deg < 1.0
