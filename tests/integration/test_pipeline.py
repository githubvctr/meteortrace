"""Integration tests for `meteortrace.pipeline.run_trail_analysis`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

import meteortrace
from meteortrace.image import read_image_metadata
from meteortrace.pipeline import build_report_sections, run_trail_analysis
from meteortrace.pixels import PixelSpace
from meteortrace.provenance import build_file_record
from meteortrace.selection import (
    SELECTION_SCHEMA_VERSION,
    ManualSelectionRecord,
    PixelClick,
    save_selection,
)
from meteortrace.trajectory import ProvisionalRadiantModel


def _build_fixtures(
    tmp_path: Path, width: int = 200, height: int = 300
) -> dict[str, Path]:
    image_path = tmp_path / "solver.png"
    Image.new("RGB", (width, height), color=(10, 10, 10)).save(image_path)

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
    wcs_path = tmp_path / "wcs.fits"
    fits.PrimaryHDU(header=header).writeto(wcs_path)

    wcs = WCS(header)
    rng = np.random.default_rng(11)
    n = 25
    field_x = rng.uniform(5, width - 5, n)
    field_y = rng.uniform(5, height - 5, n)
    ra, dec = wcs.all_pix2world(field_x - 1, field_y - 1, 0)
    noise_deg = 0.3 / 3600.0
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
    corr_path = tmp_path / "corr.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(columns)]).writeto(
        corr_path
    )

    image_record = build_file_record(image_path, role="solver_image")
    wcs_record = build_file_record(wcs_path, role="wcs")
    image_metadata = read_image_metadata(image_path, role="solver_image")

    start_clicks = tuple(
        PixelClick(x=80.0 + i * 0.2, y=100.0 - i * 0.1) for i in range(5)
    )
    end_clicks = tuple(
        PixelClick(x=120.0 + i * 0.1, y=200.0 + i * 0.3) for i in range(5)
    )
    selection = ManualSelectionRecord(
        schema_version=SELECTION_SCHEMA_VERSION,
        source_image_name=image_path.name,
        source_image_role="direct_solver_image",
        source_image_sha256=image_record.sha256,
        wcs_sha256=wcs_record.sha256,
        image_width=image_metadata.encoded_width,
        image_height=image_metadata.encoded_height,
        pixel_space=PixelSpace.WCS_SOLVED.value,
        observed_direction="start_to_end",
        start_clicks=start_clicks,
        end_clicks=end_clicks,
        selection_method="synthetic_test_seam",
        software_version=meteortrace.__version__,
    )
    selection_path = tmp_path / "selection.json"
    save_selection(selection, selection_path)

    return {
        "image": image_path,
        "wcs": wcs_path,
        "correspondences": corr_path,
        "selection": selection_path,
    }


def test_run_trail_analysis_end_to_end(tmp_path: Path) -> None:
    fixtures = _build_fixtures(tmp_path)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )

    result = run_trail_analysis(
        fixtures["image"],
        fixtures["wcs"],
        fixtures["correspondences"],
        fixtures["selection"],
        radiant_model,
        n_samples=500,
        seed=42,
    )

    assert result.analysis["schema_version"] == "1.0"
    assert "mean_result" in result.analysis
    assert "wcs_validation" in result.analysis
    assert "selection_uncertainty" in result.analysis
    assert result.monte_carlo_summary.n_samples_used <= 500


def test_run_trail_analysis_rejects_selection_from_different_image(
    tmp_path: Path,
) -> None:
    fixtures = _build_fixtures(tmp_path)
    other_image = tmp_path / "other.png"
    Image.new("RGB", (200, 300), color=(99, 99, 99)).save(other_image)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )

    with pytest.raises(ValueError):
        run_trail_analysis(
            other_image,
            fixtures["wcs"],
            fixtures["correspondences"],
            fixtures["selection"],
            radiant_model,
            n_samples=100,
            seed=1,
        )


def test_build_report_sections_contains_expected_topics(tmp_path: Path) -> None:
    fixtures = _build_fixtures(tmp_path)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )
    result = run_trail_analysis(
        fixtures["image"],
        fixtures["wcs"],
        fixtures["correspondences"],
        fixtures["selection"],
        radiant_model,
        n_samples=200,
        seed=7,
    )
    sections = build_report_sections(result)
    assert set(sections) == {
        "Observations",
        "Image-derived measurements",
        "Model inputs",
        "Selection-only uncertainty",
        "WCS internal residuals",
        "Supported conclusion",
        "Unsupported interpretations",
    }
    assert "provisional" in sections["Model inputs"].lower()
    assert "in-sample" in sections["WCS internal residuals"]
