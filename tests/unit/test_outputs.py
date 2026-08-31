"""Unit tests for `meteortrace.outputs`."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from astropy.io import fits
from PIL import Image

from meteortrace.astrometry import load_wcs, resolve_celestial_frame
from meteortrace.contracts import CelestialCoordinate, ObservedTrail, ShowerRadiant
from meteortrace.outputs import (
    generate_image_overlay_png,
    generate_radiant_geometry_png,
    write_analysis_json,
    write_provenance_json,
    write_report_md,
    write_trajectory_csv,
)
from meteortrace.pixels import PixelSpace
from meteortrace.selection import (
    SELECTION_SCHEMA_VERSION,
    ManualSelectionRecord,
    PixelClick,
)
from meteortrace.trajectory import ProvisionalRadiantModel, compute_mean_trajectory
from meteortrace.uncertainty import compute_endpoint_statistics


def _trail() -> ObservedTrail:
    return ObservedTrail(
        CelestialCoordinate(ra_deg=331.81, dec_deg=55.02),
        CelestialCoordinate(ra_deg=309.93, dec_deg=42.20),
    )


def test_write_analysis_json_is_valid_and_deterministic(tmp_path: Path) -> None:
    data = {"b": 2, "a": 1, "nested": {"z": 1, "y": 2}}
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    write_analysis_json(path_a, data)
    write_analysis_json(path_b, data)
    assert path_a.read_text() == path_b.read_text()
    assert json.loads(path_a.read_text()) == data
    # keys sorted deterministically
    assert list(json.loads(path_a.read_text()).keys()) == ["a", "b", "nested"]


def test_write_provenance_json_round_trips(tmp_path: Path) -> None:
    data = {"seed": 1, "files": []}
    path = tmp_path / "provenance.json"
    write_provenance_json(path, data)
    assert json.loads(path.read_text()) == data


def test_write_trajectory_csv_schema_and_point_count(tmp_path: Path) -> None:
    trail = _trail()
    path = tmp_path / "trajectory.csv"
    write_trajectory_csv(path, trail, n_points=50)

    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 50
    assert set(rows[0].keys()) == {
        "index",
        "along_track_deg",
        "ra_icrs_deg",
        "dec_icrs_deg",
    }
    assert float(rows[0]["ra_icrs_deg"]) == pytest.approx(331.81, abs=1e-2)
    assert float(rows[-1]["ra_icrs_deg"]) == pytest.approx(309.93, abs=1e-2)


def _write_wcs(tmp_path: Path, width: int = 100, height: int = 60) -> Path:
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


def test_generate_image_overlay_png_creates_nonempty_file(tmp_path: Path) -> None:
    width, height = 100, 60
    image_path = tmp_path / "solver.png"
    Image.new("RGB", (width, height), color=(5, 5, 5)).save(image_path)

    start_clicks = tuple(
        PixelClick(x=10.0 + i * 0.2, y=10.0 - i * 0.1) for i in range(3)
    )
    end_clicks = tuple(PixelClick(x=80.0 + i * 0.1, y=50.0 + i * 0.2) for i in range(3))
    selection = ManualSelectionRecord(
        schema_version=SELECTION_SCHEMA_VERSION,
        source_image_name=image_path.name,
        source_image_role="direct_solver_image",
        source_image_sha256="a" * 64,
        wcs_sha256="b" * 64,
        image_width=width,
        image_height=height,
        pixel_space=PixelSpace.WCS_SOLVED.value,
        observed_direction="start_to_end",
        start_clicks=start_clicks,
        end_clicks=end_clicks,
        selection_method="test",
        software_version="0.3.0",
    )
    start_stats = compute_endpoint_statistics(start_clicks)
    end_stats = compute_endpoint_statistics(end_clicks)

    output_path = tmp_path / "overlay.png"
    generate_image_overlay_png(
        output_path, image_path, selection, start_stats, end_stats
    )

    assert output_path.is_file()
    assert output_path.stat().st_size > 0


def test_generate_radiant_geometry_png_creates_nonempty_file(tmp_path: Path) -> None:
    wcs_path = _write_wcs(tmp_path)
    wcs, summary = load_wcs(wcs_path)
    frame, _ = resolve_celestial_frame(wcs, summary)
    from meteortrace.pixels import PixelCoordinate

    start = PixelCoordinate(x=40.0, y=20.0, space=PixelSpace.WCS_SOLVED)
    end = PixelCoordinate(x=60.0, y=40.0, space=PixelSpace.WCS_SOLVED)
    radiant_model = ProvisionalRadiantModel(
        name="Test radiant", ra_deg=48.0, dec_deg=58.0, frame="icrs"
    )
    mean_result = compute_mean_trajectory(wcs, frame, start, end, radiant_model)
    trail = ObservedTrail(mean_result.start_icrs, mean_result.end_icrs)
    radiant = ShowerRadiant(
        name="Test radiant", coordinate=CelestialCoordinate(48.0, 58.0)
    )

    output_path = tmp_path / "radiant.png"
    generate_radiant_geometry_png(output_path, trail, radiant, mean_result)

    assert output_path.is_file()
    assert output_path.stat().st_size > 0


def test_write_report_md_contains_all_sections(tmp_path: Path) -> None:
    sections = {"Observations": "Some text.", "Model inputs": "Other text."}
    path = tmp_path / "report.md"
    write_report_md(path, sections)
    text = path.read_text()
    assert "# MeteorTrace trail analysis report" in text
    assert "## Observations" in text
    assert "Some text." in text
    assert "## Model inputs" in text
