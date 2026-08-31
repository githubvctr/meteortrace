"""Integration tests for the `meteortrace select-trail` and `analyze-trail` CLIs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from meteortrace.cli import main
from meteortrace.selection import PixelClick


def _build_direct_fixtures(
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
    rng = np.random.default_rng(21)
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

    return {"image": image_path, "wcs": wcs_path, "correspondences": corr_path}


def test_select_trail_writes_valid_selection(tmp_path: Path) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    output = tmp_path / "selection.json"

    start_clicks = tuple(
        PixelClick(x=80.0 + i * 0.2, y=100.0 - i * 0.1) for i in range(3)
    )
    end_clicks = tuple(
        PixelClick(x=120.0 + i * 0.1, y=200.0 + i * 0.3) for i in range(3)
    )

    with patch(
        "meteortrace.cli.collect_selection_via_matplotlib",
        return_value=(start_clicks, end_clicks),
    ):
        exit_code = main(
            [
                "select-trail",
                "--image",
                str(fixtures["image"]),
                "--wcs",
                str(fixtures["wcs"]),
                "--repeats",
                "3",
                "--output",
                str(output),
            ]
        )

    assert exit_code == 0
    assert output.is_file()
    data = json.loads(output.read_text())
    assert data["schema_version"] == "1.0"
    assert len(data["start_clicks"]) == 3
    assert len(data["end_clicks"]) == 3


def test_select_trail_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    output = tmp_path / "selection.json"
    output.write_text("existing")

    exit_code = main(
        [
            "select-trail",
            "--image",
            str(fixtures["image"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--repeats",
            "3",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert output.read_text() == "existing"


def test_select_trail_cancellation_writes_nothing(tmp_path: Path) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    output = tmp_path / "selection.json"

    from meteortrace.interactive_selection import SelectionCancelledError

    with patch(
        "meteortrace.cli.collect_selection_via_matplotlib",
        side_effect=SelectionCancelledError("cancelled"),
    ):
        exit_code = main(
            [
                "select-trail",
                "--image",
                str(fixtures["image"]),
                "--wcs",
                str(fixtures["wcs"]),
                "--repeats",
                "3",
                "--output",
                str(output),
            ]
        )

    assert exit_code == 3
    assert not output.exists()


def _write_selection_via_cli(
    tmp_path: Path, fixtures: dict[str, Path], n: int = 5
) -> Path:
    start_clicks = tuple(
        PixelClick(x=80.0 + i * 0.2, y=100.0 - i * 0.1) for i in range(n)
    )
    end_clicks = tuple(
        PixelClick(x=120.0 + i * 0.1, y=200.0 + i * 0.3) for i in range(n)
    )
    output = tmp_path / "selection.json"
    with patch(
        "meteortrace.cli.collect_selection_via_matplotlib",
        return_value=(start_clicks, end_clicks),
    ):
        main(
            [
                "select-trail",
                "--image",
                str(fixtures["image"]),
                "--wcs",
                str(fixtures["wcs"]),
                "--repeats",
                str(n),
                "--output",
                str(output),
            ]
        )
    return output


def test_analyze_trail_produces_all_outputs(tmp_path: Path) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    selection_path = _write_selection_via_cli(tmp_path, fixtures)
    output_dir = tmp_path / "analysis"

    exit_code = main(
        [
            "analyze-trail",
            "--image",
            str(fixtures["image"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--correspondences",
            str(fixtures["correspondences"]),
            "--selection",
            str(selection_path),
            "--radiant-name",
            "Perseids (provisional)",
            "--radiant-ra-deg",
            "48.0",
            "--radiant-dec-deg",
            "58.0",
            "--radiant-frame",
            "icrs",
            "--samples",
            "300",
            "--seed",
            "20260812",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    for name in (
        "analysis.json",
        "trajectory.csv",
        "image_overlay.png",
        "radiant_geometry.png",
        "report.md",
        "provenance.json",
    ):
        assert (output_dir / name).is_file(), f"missing {name}"

    analysis = json.loads((output_dir / "analysis.json").read_text())
    assert analysis["schema_version"] == "1.0"
    assert "provisional_radiant" in analysis


def test_analyze_trail_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    selection_path = _write_selection_via_cli(tmp_path, fixtures)
    output_dir = tmp_path / "analysis"
    output_dir.mkdir()
    (output_dir / "analysis.json").write_text("existing")

    exit_code = main(
        [
            "analyze-trail",
            "--image",
            str(fixtures["image"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--correspondences",
            str(fixtures["correspondences"]),
            "--selection",
            str(selection_path),
            "--radiant-name",
            "Perseids (provisional)",
            "--radiant-ra-deg",
            "48.0",
            "--radiant-dec-deg",
            "58.0",
            "--samples",
            "100",
            "--seed",
            "1",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 2
    assert (output_dir / "analysis.json").read_text() == "existing"


def test_analyze_trail_no_absolute_paths_or_gps(tmp_path: Path) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    selection_path = _write_selection_via_cli(tmp_path, fixtures)
    output_dir = tmp_path / "analysis"

    exit_code = main(
        [
            "analyze-trail",
            "--image",
            str(fixtures["image"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--correspondences",
            str(fixtures["correspondences"]),
            "--selection",
            str(selection_path),
            "--radiant-name",
            "Perseids (provisional)",
            "--radiant-ra-deg",
            "48.0",
            "--radiant-dec-deg",
            "58.0",
            "--samples",
            "100",
            "--seed",
            "1",
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    for name in ("analysis.json", "provenance.json", "report.md"):
        text = (output_dir / name).read_text()
        assert str(tmp_path) not in text
        assert "gps" not in text.lower()


def test_analyze_trail_missing_selection_fails_with_nonzero_exit(
    tmp_path: Path,
) -> None:
    fixtures = _build_direct_fixtures(tmp_path)
    output_dir = tmp_path / "analysis"

    exit_code = main(
        [
            "analyze-trail",
            "--image",
            str(fixtures["image"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--correspondences",
            str(fixtures["correspondences"]),
            "--selection",
            str(tmp_path / "does_not_exist.json"),
            "--radiant-name",
            "Perseids (provisional)",
            "--radiant-ra-deg",
            "48.0",
            "--radiant-dec-deg",
            "58.0",
            "--samples",
            "100",
            "--seed",
            "1",
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 1
    assert not (output_dir / "analysis.json").exists()
