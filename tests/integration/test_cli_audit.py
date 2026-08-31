"""Integration tests for the `meteortrace audit-inputs` CLI."""

from __future__ import annotations

import json
from pathlib import Path

from astropy.io import fits
from PIL import Image

from meteortrace.cli import main


def _make_jpeg(
    path: Path,
    size: tuple[int, int],
    gps: dict | None = None,
    color: tuple[int, int, int] = (1, 2, 3),
) -> None:
    image = Image.new("RGB", size, color=color)
    exif = image.getexif()
    exif[274] = 1
    exif[271] = "Apple"
    exif[272] = "iPhone Test"
    exif[0x8769] = {
        36867: "2026:08:12 00:34:15",
        36881: "+02:00",
        37386: 6.0,
        41989: 24,
        42036: "Test lens",
    }
    if gps is not None:
        exif[0x8825] = gps
    image.save(path, exif=exif.tobytes())


def _make_wcs_fits(path: Path, width: int, height: int) -> None:
    header = fits.Header()
    header["WCSAXES"] = 2
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRPIX1"] = width / 2
    header["CRPIX2"] = height / 2
    header["CRVAL1"] = 10.0
    header["CRVAL2"] = 20.0
    header["CD1_1"] = -0.001
    header["CD1_2"] = 0.0
    header["CD2_1"] = 0.0
    header["CD2_2"] = 0.001
    header["IMAGEW"] = width
    header["IMAGEH"] = height
    fits.PrimaryHDU(header=header).writeto(path)


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    reference = tmp_path / "reference.jpg"
    target = tmp_path / "target.jpg"
    derived = tmp_path / "derived.jpg"
    wcs_path = tmp_path / "solution.fits"

    _make_jpeg(reference, (100, 60), gps={1: "N", 2: (37.7749, 0.0, 0.0)})
    _make_jpeg(target, (100, 60), gps={1: "N", 2: (37.7749, 0.0, 0.0)}, color=(9, 8, 7))
    _make_jpeg(derived, (100, 60))
    _make_wcs_fits(wcs_path, 100, 60)

    return {
        "reference": reference,
        "target": target,
        "derived": derived,
        "wcs": wcs_path,
    }


def test_successful_audit_produces_expected_output(tmp_path: Path) -> None:
    fixtures = _fixture_paths(tmp_path)
    output = tmp_path / "results" / "audit.json"

    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(fixtures["reference"]),
            "--target-image",
            str(fixtures["target"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--derived-image",
            str(fixtures["derived"]),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.is_file()

    result = json.loads(output.read_text())
    assert result["schema_version"] == "2.0"
    assert "package_version" in result
    assert result["reference_grid_assessment"]["status"] in {
        "direct_match",
        "transform_required",
        "incompatible",
        "insufficient_evidence",
    }
    assert result["target_transfer_assessment"]["status"] in {
        "direct_match",
        "registration_required",
        "incompatible",
        "insufficient_evidence",
    }
    assert result["target_transfer_assessment"]["status"] == "registration_required"
    assert "compatibility" not in result


def test_overwrite_is_refused_without_flag(tmp_path: Path) -> None:
    fixtures = _fixture_paths(tmp_path)
    output = tmp_path / "audit.json"
    output.write_text("existing content")

    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(fixtures["reference"]),
            "--target-image",
            str(fixtures["target"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert output.read_text() == "existing content"


def test_overwrite_succeeds_with_explicit_flag(tmp_path: Path) -> None:
    fixtures = _fixture_paths(tmp_path)
    output = tmp_path / "audit.json"
    output.write_text("existing content")

    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(fixtures["reference"]),
            "--target-image",
            str(fixtures["target"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--output",
            str(output),
            "--overwrite",
        ]
    )

    assert exit_code == 0
    result = json.loads(output.read_text())
    assert result["schema_version"] == "2.0"


def test_output_contains_no_absolute_paths_or_gps_values(tmp_path: Path) -> None:
    fixtures = _fixture_paths(tmp_path)
    output = tmp_path / "audit.json"

    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(fixtures["reference"]),
            "--target-image",
            str(fixtures["target"]),
            "--wcs",
            str(fixtures["wcs"]),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    text = output.read_text()
    assert str(tmp_path) not in text
    assert "37.7749" not in text  # the fixture's synthetic GPS latitude value
    assert '"has_gps": true' in text


def test_missing_wcs_file_fails_with_non_zero_exit(tmp_path: Path) -> None:
    fixtures = _fixture_paths(tmp_path)
    output = tmp_path / "audit.json"

    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(fixtures["reference"]),
            "--target-image",
            str(fixtures["target"]),
            "--wcs",
            str(tmp_path / "does_not_exist.fits"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    assert not output.exists()


def test_transposed_reference_grid_yields_transform_required_not_direct_match(
    tmp_path: Path,
) -> None:
    # Mirrors the real 2026 Perseid session shape: a portrait-decoded
    # reference image against a landscape-solved WCS grid.
    reference = tmp_path / "reference.jpg"
    target = tmp_path / "target.jpg"
    wcs_path = tmp_path / "solution.fits"

    _make_jpeg(reference, (60, 100))
    _make_jpeg(target, (60, 100), color=(9, 8, 7))
    _make_wcs_fits(wcs_path, 100, 60)

    output = tmp_path / "audit.json"
    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(reference),
            "--target-image",
            str(target),
            "--wcs",
            str(wcs_path),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    result = json.loads(output.read_text())
    assert result["reference_grid_assessment"]["status"] == "transform_required"
    assert result["target_transfer_assessment"]["status"] == "registration_required"


def test_same_file_as_reference_and_target_yields_target_direct_match(
    tmp_path: Path,
) -> None:
    same_file = tmp_path / "same.jpg"
    wcs_path = tmp_path / "solution.fits"
    _make_jpeg(same_file, (100, 60))
    _make_wcs_fits(wcs_path, 100, 60)

    output = tmp_path / "audit.json"
    exit_code = main(
        [
            "audit-inputs",
            "--reference-image",
            str(same_file),
            "--target-image",
            str(same_file),
            "--wcs",
            str(wcs_path),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    result = json.loads(output.read_text())
    assert result["reference_grid_assessment"]["status"] == "direct_match"
    assert result["target_transfer_assessment"]["status"] == "direct_match"
