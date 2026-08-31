"""Unit tests for `meteortrace.correspondence`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from meteortrace.correspondence import (
    CorrespondenceSchemaError,
    PixelOriginAmbiguityError,
    determine_pixel_origin_convention,
    load_correspondences,
    validate_wcs_correspondence,
)


def _make_wcs(width: int = 200, height: int = 300) -> WCS:
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
    return WCS(header)


def _write_corr_fits(
    path: Path,
    wcs: WCS,
    n: int = 20,
    origin_offset: float = 1.0,
    catalogue_noise_arcsec: float = 0.5,
    seed: int = 1,
    width: int = 200,
    height: int = 300,
) -> None:
    rng = np.random.default_rng(seed)
    field_x = rng.uniform(5, width - 5, n)
    field_y = rng.uniform(5, height - 5, n)
    ra, dec = wcs.all_pix2world(field_x - origin_offset, field_y - origin_offset, 0)
    noise_deg = catalogue_noise_arcsec / 3600.0
    index_ra = ra + rng.normal(0, noise_deg, n)
    index_dec = dec + rng.normal(0, noise_deg, n)
    columns = [
        fits.Column(name="field_x", format="D", array=field_x),
        fits.Column(name="field_y", format="D", array=field_y),
        fits.Column(name="field_ra", format="D", array=ra),
        fits.Column(name="field_dec", format="D", array=dec),
        fits.Column(name="index_ra", format="D", array=index_ra),
        fits.Column(name="index_dec", format="D", array=index_dec),
    ]
    hdu = fits.BinTableHDU.from_columns(columns)
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(path)


def test_load_correspondences_reads_required_columns(tmp_path: Path) -> None:
    wcs = _make_wcs()
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs)
    data = load_correspondences(path)
    assert set(data) == {
        "field_x",
        "field_y",
        "field_ra",
        "field_dec",
        "index_ra",
        "index_dec",
    }
    assert len(data["field_x"]) == 20


def test_load_correspondences_missing_column_raises(tmp_path: Path) -> None:
    columns = [fits.Column(name="field_x", format="D", array=np.array([1.0, 2.0]))]
    hdu = fits.BinTableHDU.from_columns(columns)
    path = tmp_path / "bad_corr.fits"
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(path)
    with pytest.raises(CorrespondenceSchemaError):
        load_correspondences(path)


def test_load_correspondences_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_correspondences(tmp_path / "does_not_exist.fits")


def test_fits_1_based_origin_is_established(tmp_path: Path) -> None:
    wcs = _make_wcs()
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs, origin_offset=1.0)
    data = load_correspondences(path)
    offset, evidence = determine_pixel_origin_convention(
        wcs, data["field_x"], data["field_y"], data["field_ra"], data["field_dec"]
    )
    assert offset == 1.0
    assert evidence["median_residual_arcsec_if_fits_1_based"] < 1e-3
    assert evidence["median_residual_arcsec_if_zero_based"] > 1.0


def test_zero_based_origin_is_established(tmp_path: Path) -> None:
    wcs = _make_wcs()
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs, origin_offset=0.0)
    data = load_correspondences(path)
    offset, evidence = determine_pixel_origin_convention(
        wcs, data["field_x"], data["field_y"], data["field_ra"], data["field_dec"]
    )
    assert offset == 0.0
    assert evidence["median_residual_arcsec_if_zero_based"] < 1e-3
    assert evidence["median_residual_arcsec_if_fits_1_based"] > 1.0


def test_ambiguous_pixel_origin_raises(tmp_path: Path) -> None:
    # A near-square-pixel-scale WCS at a location where a 1-pixel origin
    # shift produces a sub-arcsecond difference makes both hypotheses
    # equally (un)informative; simulate this directly by feeding
    # field_ra/dec that don't correspond to either hypothesis.
    wcs = _make_wcs()
    n = 10
    rng = np.random.default_rng(3)
    field_x = rng.uniform(5, 195, n)
    field_y = rng.uniform(5, 295, n)
    # Unrelated random sky positions: neither offset reproduces them.
    field_ra = rng.uniform(40, 56, n)
    field_dec = rng.uniform(50, 66, n)
    with pytest.raises(PixelOriginAmbiguityError):
        determine_pixel_origin_convention(wcs, field_x, field_y, field_ra, field_dec)


def test_validate_wcs_correspondence_reports_residual_statistics(
    tmp_path: Path,
) -> None:
    wcs = _make_wcs(width=200, height=300)
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs, n=50, origin_offset=1.0, catalogue_noise_arcsec=0.3)
    data = load_correspondences(path)

    report = validate_wcs_correspondence(
        wcs,
        data,
        solver_image_width=200,
        solver_image_height=300,
        wcs_width=200,
        wcs_height=300,
    )
    assert report.pixel_origin_convention == "fits_1_based"
    assert report.residuals.match_count == 50
    assert report.residuals.all_finite is True
    assert report.residuals.median_arcsec < 5.0
    assert report.residuals.rms_arcsec >= report.residuals.median_arcsec * 0.1
    assert report.dimensions_agree_with_solver_image is True
    assert not any("disagree" in w for w in report.warnings)


def test_validate_wcs_correspondence_flags_dimension_disagreement(
    tmp_path: Path,
) -> None:
    wcs = _make_wcs(width=200, height=300)
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs, n=20, origin_offset=1.0)
    data = load_correspondences(path)

    report = validate_wcs_correspondence(
        wcs,
        data,
        solver_image_width=999,
        solver_image_height=999,
        wcs_width=200,
        wcs_height=300,
    )
    assert report.dimensions_agree_with_solver_image is False
    assert any("disagree" in w for w in report.warnings)


def test_validate_wcs_correspondence_flags_large_residuals(tmp_path: Path) -> None:
    wcs = _make_wcs(width=200, height=300)
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs, n=30, origin_offset=1.0, catalogue_noise_arcsec=50.0)
    data = load_correspondences(path)

    report = validate_wcs_correspondence(
        wcs,
        data,
        solver_image_width=200,
        solver_image_height=300,
        wcs_width=200,
        wcs_height=300,
    )
    assert report.residuals.median_arcsec > 5.0
    assert any("large" in w.lower() for w in report.warnings)


def test_field_coverage_reports_extent(tmp_path: Path) -> None:
    wcs = _make_wcs(width=200, height=300)
    path = tmp_path / "corr.fits"
    _write_corr_fits(path, wcs, n=30, origin_offset=1.0, width=200, height=300)
    data = load_correspondences(path)
    report = validate_wcs_correspondence(
        wcs,
        data,
        solver_image_width=200,
        solver_image_height=300,
        wcs_width=200,
        wcs_height=300,
    )
    assert 0.0 < report.coverage.x_coverage_fraction <= 1.0
    assert 0.0 < report.coverage.y_coverage_fraction <= 1.0
    assert report.coverage.x_min < report.coverage.x_max
