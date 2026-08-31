"""Read-only ingestion of an Astrometry.net WCS/FITS solution.

The FITS file is opened read-only and never modified. Astrometry.net
solutions are frequently header-only (no pixel data attached), so pixel
dimensions must be resolved from whichever of several possible metadata
sources are present, and any disagreement between them is reported rather
than silently resolved by picking one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from astropy.io import fits
from astropy.io.fits import Header
from astropy.wcs import WCS

from meteortrace.contracts import CelestialCoordinate
from meteortrace.pixels import PixelCoordinate, PixelSpace, require_space


class DimensionResolutionError(ValueError):
    """Raised when pixel dimensions cannot be resolved unambiguously."""


class NonCelestialWcsError(ValueError):
    """Raised when a WCS solution has no celestial axes to convert against."""


def _resolve_pixel_dimensions(
    header: Header, wcs: WCS
) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Resolve solved image (width, height) from all available header sources.

    Raises
    ------
    DimensionResolutionError
        If no dimension source is present, or if present sources disagree.
    """
    sources: dict[str, tuple[int, int]] = {}
    if "IMAGEW" in header and "IMAGEH" in header:
        sources["IMAGEW_IMAGEH"] = (int(header["IMAGEW"]), int(header["IMAGEH"]))
    if "NAXIS1" in header and "NAXIS2" in header:
        sources["NAXIS1_NAXIS2"] = (int(header["NAXIS1"]), int(header["NAXIS2"]))
    if wcs.pixel_shape is not None:
        sources["wcs_pixel_shape"] = (int(wcs.pixel_shape[0]), int(wcs.pixel_shape[1]))

    if not sources:
        raise DimensionResolutionError(
            "No pixel-dimension source found in the WCS header "
            "(checked IMAGEW/IMAGEH, NAXIS1/NAXIS2, and the WCS pixel shape)."
        )
    distinct = set(sources.values())
    if len(distinct) > 1:
        raise DimensionResolutionError(
            f"Disagreeing pixel-dimension sources in WCS header: {sources}."
        )
    (width, height) = next(iter(distinct))
    return width, height, sources


@dataclass(frozen=True)
class WcsSummary:
    """Non-sensitive, JSON-serializable summary of an ingested WCS solution."""

    width: int
    height: int
    dimension_sources: dict[str, tuple[int, int]]
    naxis: int
    ctype: tuple[str, str]
    crpix: tuple[float, float]
    crval: tuple[float, float]
    cd_matrix: tuple[tuple[float, float], tuple[float, float]] | None
    header_radesys: str | None
    astropy_inferred_radesys: str | None
    equinox: float | None
    has_celestial: bool
    has_sip: bool
    sip_orders: tuple[int, int] | None

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "dimension_sources": {
                key: list(value) for key, value in self.dimension_sources.items()
            },
            "naxis": self.naxis,
            "ctype": list(self.ctype),
            "crpix": list(self.crpix),
            "crval": list(self.crval),
            "cd_matrix": (
                [list(row) for row in self.cd_matrix] if self.cd_matrix else None
            ),
            "header_radesys": self.header_radesys,
            "astropy_inferred_radesys": self.astropy_inferred_radesys,
            "equinox": self.equinox,
            "has_celestial": self.has_celestial,
            "has_sip": self.has_sip,
            "sip_orders": list(self.sip_orders) if self.sip_orders else None,
        }


def load_wcs(path: Path) -> tuple[WCS, WcsSummary]:
    """Load a WCS solution read-only and summarize its metadata.

    Raises
    ------
    FileNotFoundError
        If `path` does not exist.
    DimensionResolutionError
        If solved pixel dimensions cannot be resolved unambiguously.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path.name!r}")

    with fits.open(path, mode="readonly") as hdul:
        header = hdul[0].header.copy()

    wcs = WCS(header)
    width, height, sources = _resolve_pixel_dimensions(header, wcs)

    cd_matrix = None
    if wcs.wcs.has_cd():
        cd = wcs.wcs.cd
        cd_matrix = (
            (float(cd[0, 0]), float(cd[0, 1])),
            (float(cd[1, 0]), float(cd[1, 1])),
        )

    sip_orders = None
    if wcs.sip is not None:
        sip_orders = (int(wcs.sip.a_order), int(wcs.sip.b_order))

    equinox = header.get("EQUINOX")
    summary = WcsSummary(
        width=width,
        height=height,
        dimension_sources=sources,
        naxis=wcs.naxis,
        ctype=(str(wcs.wcs.ctype[0]), str(wcs.wcs.ctype[1])),
        crpix=(float(wcs.wcs.crpix[0]), float(wcs.wcs.crpix[1])),
        crval=(float(wcs.wcs.crval[0]), float(wcs.wcs.crval[1])),
        cd_matrix=cd_matrix,
        header_radesys=header.get("RADESYS"),
        astropy_inferred_radesys=(wcs.wcs.radesys or None),
        equinox=float(equinox) if equinox is not None else None,
        has_celestial=bool(wcs.has_celestial),
        has_sip=wcs.sip is not None,
        sip_orders=sip_orders,
    )
    return wcs, summary


def pixel_to_sky(wcs: WCS, point: PixelCoordinate) -> CelestialCoordinate:
    """Convert a `WCS_SOLVED` pixel coordinate to a celestial coordinate.

    Uses explicit ``origin=0`` semantics (zero-based pixel indexing).

    Raises
    ------
    ValueError
        If `point` is not in the `WCS_SOLVED` pixel space.
    NonCelestialWcsError
        If the WCS has no celestial axes.
    """
    require_space(point, PixelSpace.WCS_SOLVED)
    if not wcs.has_celestial:
        raise NonCelestialWcsError("WCS solution has no celestial axes.")
    ra, dec = wcs.all_pix2world(point.x, point.y, 0)
    return CelestialCoordinate(ra_deg=float(ra), dec_deg=float(dec))


def sky_to_pixel(wcs: WCS, coordinate: CelestialCoordinate) -> PixelCoordinate:
    """Convert a celestial coordinate to a `WCS_SOLVED` pixel coordinate.

    Uses explicit ``origin=0`` semantics (zero-based pixel indexing).

    Raises
    ------
    NonCelestialWcsError
        If the WCS has no celestial axes.
    ValueError
        If the solved pixel position is non-finite.
    """
    if not wcs.has_celestial:
        raise NonCelestialWcsError("WCS solution has no celestial axes.")
    x, y = wcs.all_world2pix(coordinate.ra_deg, coordinate.dec_deg, 0)
    x, y = float(x), float(y)
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(
            f"WCS solved a non-finite pixel position (x={x}, y={y}) for "
            f"ra_deg={coordinate.ra_deg}, dec_deg={coordinate.dec_deg}."
        )
    return PixelCoordinate(x=x, y=y, space=PixelSpace.WCS_SOLVED)


def roundtrip_pixel_error(wcs: WCS, point: PixelCoordinate) -> float:
    """Euclidean pixel error from converting `point` to sky and back."""
    sky = pixel_to_sky(wcs, point)
    back = sky_to_pixel(wcs, sky)
    return math.hypot(back.x - point.x, back.y - point.y)


def is_within_bounds(point: PixelCoordinate, width: int, height: int) -> bool:
    """Whether `point` falls within an image frame of `width` x `height`.

    Deliberately separate from coordinate transformation: a WCS solution
    can be mathematically valid far outside the pixel grid it was solved
    for, so boundedness is a distinct question. Uses the pixel-centre
    convention, where pixel index ``0`` spans ``[-0.5, 0.5)``.
    """
    return -0.5 <= point.x <= width - 0.5 and -0.5 <= point.y <= height - 0.5
