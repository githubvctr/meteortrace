"""Validation of an ingested WCS against its Astrometry.net correspondence table.

Astrometry.net's ``corr.fits`` records, for each matched source, the
detected image pixel position (``field_x``/``field_y``), the WCS-applied
sky position at that pixel (``field_ra``/``field_dec``), the predicted
image pixel position of the matched reference star
(``index_x``/``index_y``), and that reference star's catalogue sky
position (``index_ra``/``index_dec``). Comparing a WCS's own
pixel-to-sky conversion of ``field_x``/``field_y`` against
``index_ra``/``index_dec`` validates that WCS against its own solve
inputs.

These residuals are **in-sample solution diagnostics**: the same
correspondences that produced the fit are being re-evaluated against it.
They are internal-consistency evidence, not an independent, unbiased
estimate of external astrometric error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from meteortrace.pixels import PixelCoordinate, PixelSpace

# corr.fits columns required for WCS validation, per the Astrometry.net
# BinTableHDU schema observed in practice (verified against a real solve,
# not assumed): detected-source pixel position, and the matched
# reference catalogue's true sky position.
_REQUIRED_COLUMNS = (
    "field_x",
    "field_y",
    "field_ra",
    "field_dec",
    "index_ra",
    "index_dec",
)


class CorrespondenceSchemaError(ValueError):
    """Raised when a corr.fits table is missing an expected column."""


class PixelOriginAmbiguityError(ValueError):
    """Raised when the pixel-origin convention cannot be established from evidence."""


@dataclass(frozen=True)
class ResidualStatistics:
    """Robust angular residual statistics, in arcseconds."""

    match_count: int
    median_arcsec: float
    p68_arcsec: float
    p95_arcsec: float
    max_arcsec: float
    rms_arcsec: float
    all_finite: bool

    def to_dict(self) -> dict:
        return {
            "match_count": self.match_count,
            "median_arcsec": self.median_arcsec,
            "p68_arcsec": self.p68_arcsec,
            "p95_arcsec": self.p95_arcsec,
            "max_arcsec": self.max_arcsec,
            "rms_arcsec": self.rms_arcsec,
            "all_finite": self.all_finite,
        }


@dataclass(frozen=True)
class FieldCoverage:
    """Spatial extent of matched correspondences within the image frame."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    x_coverage_fraction: float
    y_coverage_fraction: float

    def to_dict(self) -> dict:
        return {
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "x_coverage_fraction": self.x_coverage_fraction,
            "y_coverage_fraction": self.y_coverage_fraction,
        }


@dataclass(frozen=True)
class WcsValidationReport:
    """Result of validating a WCS against its own correspondence table."""

    residuals: ResidualStatistics
    coverage: FieldCoverage
    pixel_origin_convention: str
    pixel_origin_evidence: dict[str, float]
    dimensions_agree_with_solver_image: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "residuals": self.residuals.to_dict(),
            "coverage": self.coverage.to_dict(),
            "pixel_origin_convention": self.pixel_origin_convention,
            "pixel_origin_evidence": self.pixel_origin_evidence,
            "dimensions_agree_with_solver_image": (
                self.dimensions_agree_with_solver_image
            ),
            "warnings": list(self.warnings),
        }


def load_correspondences(path: Path) -> dict[str, np.ndarray]:
    """Load the required columns of a corr.fits table, read-only.

    Raises
    ------
    FileNotFoundError
        If `path` does not exist.
    CorrespondenceSchemaError
        If any required column is absent.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path.name!r}")
    with fits.open(path, mode="readonly") as hdul:
        data = hdul[1].data
        columns = set(data.columns.names)
        missing = [name for name in _REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise CorrespondenceSchemaError(
                f"corr.fits table is missing expected column(s) {missing}; "
                f"found columns: {sorted(columns)}."
            )
        return {
            name: np.asarray(data[name], dtype=np.float64) for name in _REQUIRED_COLUMNS
        }


def _pixel_hypothesis_residuals(
    wcs: WCS,
    field_x: np.ndarray,
    field_y: np.ndarray,
    index_ra: np.ndarray,
    index_dec: np.ndarray,
    origin_offset: float,
) -> np.ndarray:
    """Residuals (arcsec) assuming `field_x`/`field_y` need `origin_offset` subtracted.

    `origin_offset` is ``0.0`` for the "already zero-based" hypothesis and
    ``1.0`` for the "FITS 1-based" hypothesis; both are evaluated
    explicitly rather than assumed.
    """
    ra, dec = wcs.all_pix2world(field_x - origin_offset, field_y - origin_offset, 0)
    field = SkyCoord(ra=ra, dec=dec, unit="deg")
    index = SkyCoord(ra=index_ra, dec=index_dec, unit="deg")
    return field.separation(index).arcsec


# Below this residual, our own pixel->sky conversion is considered to
# exactly reproduce Astrometry.net's own recorded field_ra/field_dec
# (floating-point/SIP-evaluation noise only).
_ORIGIN_MATCH_TOLERANCE_ARCSEC = 0.01
# Above this residual, a hypothesis is considered a clear mismatch.
_ORIGIN_MISMATCH_THRESHOLD_ARCSEC = 1.0


def determine_pixel_origin_convention(
    wcs: WCS,
    field_x: np.ndarray,
    field_y: np.ndarray,
    field_ra: np.ndarray,
    field_dec: np.ndarray,
) -> tuple[float, dict[str, float]]:
    """Determine whether `field_x`/`field_y` are zero-based or FITS 1-based.

    Both candidate conventions are evaluated by actually transforming
    pixel positions through the WCS and comparing against Astrometry.net's
    own recorded ``field_ra``/``field_dec`` (which is itself the WCS
    applied to `field_x`/`field_y` under whichever convention Astrometry.net
    used) rather than the noisier matched-catalogue position: the correct
    convention reproduces `field_ra`/`field_dec` to floating-point
    precision, while the wrong one differs by an arcsecond-scale amount.
    The convention is never assumed.

    Raises
    ------
    PixelOriginAmbiguityError
        If neither hypothesis reproduces `field_ra`/`field_dec` closely,
        or both do (so the test is uninformative).
    """
    median_zero_based = float(
        np.median(
            _pixel_hypothesis_residuals(wcs, field_x, field_y, field_ra, field_dec, 0.0)
        )
    )
    median_fits_1_based = float(
        np.median(
            _pixel_hypothesis_residuals(wcs, field_x, field_y, field_ra, field_dec, 1.0)
        )
    )
    evidence = {
        "median_residual_arcsec_if_zero_based": median_zero_based,
        "median_residual_arcsec_if_fits_1_based": median_fits_1_based,
    }

    zero_based_matches = median_zero_based < _ORIGIN_MATCH_TOLERANCE_ARCSEC
    fits_1_based_matches = median_fits_1_based < _ORIGIN_MATCH_TOLERANCE_ARCSEC
    if zero_based_matches == fits_1_based_matches:
        raise PixelOriginAmbiguityError(
            "Pixel-origin convention for corr.fits field_x/field_y could not be "
            "established against Astrometry.net's own field_ra/field_dec: "
            f"exactly one hypothesis must reproduce it closely ({evidence})."
        )
    winner, loser = (
        (0.0, median_fits_1_based) if zero_based_matches else (1.0, median_zero_based)
    )
    if loser < _ORIGIN_MISMATCH_THRESHOLD_ARCSEC:
        raise PixelOriginAmbiguityError(
            "Pixel-origin convention is not a clear mismatch for the losing "
            f"hypothesis, so the result is not conclusive ({evidence})."
        )
    return winner, evidence


def validate_wcs_correspondence(
    wcs: WCS,
    correspondences: dict[str, np.ndarray],
    solver_image_width: int,
    solver_image_height: int,
    wcs_width: int,
    wcs_height: int,
) -> WcsValidationReport:
    """Validate a WCS against its own correspondence table.

    Raises
    ------
    PixelOriginAmbiguityError
        If the pixel-origin convention cannot be established from evidence.
    """
    field_x = correspondences["field_x"]
    field_y = correspondences["field_y"]
    field_ra = correspondences["field_ra"]
    field_dec = correspondences["field_dec"]
    index_ra = correspondences["index_ra"]
    index_dec = correspondences["index_dec"]

    origin_offset, origin_evidence = determine_pixel_origin_convention(
        wcs, field_x, field_y, field_ra, field_dec
    )
    convention_name = "zero_based" if origin_offset == 0.0 else "fits_1_based"

    residual_arcsec = _pixel_hypothesis_residuals(
        wcs, field_x, field_y, index_ra, index_dec, origin_offset
    )
    all_finite = bool(np.all(np.isfinite(residual_arcsec)))
    finite_residuals = residual_arcsec[np.isfinite(residual_arcsec)]

    residuals = ResidualStatistics(
        match_count=int(len(residual_arcsec)),
        median_arcsec=float(np.median(finite_residuals)),
        p68_arcsec=float(np.percentile(finite_residuals, 68)),
        p95_arcsec=float(np.percentile(finite_residuals, 95)),
        max_arcsec=float(np.max(finite_residuals)),
        rms_arcsec=float(np.sqrt(np.mean(np.square(finite_residuals)))),
        all_finite=all_finite,
    )

    coverage = FieldCoverage(
        x_min=float(field_x.min()),
        x_max=float(field_x.max()),
        y_min=float(field_y.min()),
        y_max=float(field_y.max()),
        x_coverage_fraction=float((field_x.max() - field_x.min()) / solver_image_width),
        y_coverage_fraction=float(
            (field_y.max() - field_y.min()) / solver_image_height
        ),
    )

    dimensions_agree = (solver_image_width, solver_image_height) == (
        wcs_width,
        wcs_height,
    )

    warnings: list[str] = []
    if not dimensions_agree:
        warnings.append(
            f"Solver image dimensions ({solver_image_width}x{solver_image_height}) "
            f"disagree with WCS-resolved dimensions ({wcs_width}x{wcs_height})."
        )
    if not all_finite:
        warnings.append("One or more correspondence residuals are non-finite.")
    if residuals.median_arcsec > 5.0:
        warnings.append(
            f"Median residual ({residuals.median_arcsec:.1f} arcsec) is large for a "
            "typical Astrometry.net solve; treat this WCS's astrometric accuracy as "
            "unverified beyond internal consistency until independently checked."
        )

    return WcsValidationReport(
        residuals=residuals,
        coverage=coverage,
        pixel_origin_convention=convention_name,
        pixel_origin_evidence=origin_evidence,
        dimensions_agree_with_solver_image=dimensions_agree,
        warnings=tuple(warnings),
    )


def corr_pixel_to_meteortrace_pixel(
    x: float, y: float, origin_offset: float
) -> PixelCoordinate:
    """Convert a raw corr.fits field pixel position to MeteorTrace's `WCS_SOLVED` space.

    `origin_offset` is the value determined by
    `determine_pixel_origin_convention` (``0.0`` or ``1.0``).
    """
    return PixelCoordinate(
        x=x - origin_offset, y=y - origin_offset, space=PixelSpace.WCS_SOLVED
    )
