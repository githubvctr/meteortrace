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

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.coordinates.baseframe import BaseCoordinateFrame
from astropy.io import fits
from astropy.io.fits import Header
from astropy.wcs import WCS
from astropy.wcs.utils import wcs_to_celestial_frame

from meteortrace.contracts import CelestialCoordinate
from meteortrace.pixels import PixelCoordinate, PixelSpace, require_space


class DimensionResolutionError(ValueError):
    """Raised when pixel dimensions cannot be resolved unambiguously."""


class NonCelestialWcsError(ValueError):
    """Raised when a WCS solution has no celestial axes to convert against."""


class FrameResolutionError(ValueError):
    """Raised when a WCS's celestial reference frame cannot be resolved."""


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

    # naxis=2 selects only the celestial pixel axes: some Astrometry.net
    # products (e.g. new-image.fits) attach a 3rd, non-celestial colour-plane
    # axis that WCSLIB cannot combine with a 2D SIP distortion model.
    wcs = WCS(header, naxis=2)
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


def wcs_summaries_agree(a: WcsSummary, b: WcsSummary, tolerance: float = 1e-6) -> bool:
    """Whether two `WcsSummary` instances describe the same solved WCS.

    Compares dimensions, CTYPE, CRPIX, CRVAL, the CD matrix, header
    RADESYS and EQUINOX. Used to check that two independently ingested
    FITS products (e.g. a header-only `wcs.fits` and a pixel-bearing
    `new-image.fits`) describe a consistent solution.
    """
    if (a.width, a.height, a.ctype, a.header_radesys, a.equinox) != (
        b.width,
        b.height,
        b.ctype,
        b.header_radesys,
        b.equinox,
    ):
        return False
    if any(abs(x - y) > tolerance for x, y in zip(a.crpix, b.crpix, strict=True)):
        return False
    if any(abs(x - y) > tolerance for x, y in zip(a.crval, b.crval, strict=True)):
        return False
    if (a.cd_matrix is None) != (b.cd_matrix is None):
        return False
    if a.cd_matrix is not None and b.cd_matrix is not None:
        flat_a = [value for row in a.cd_matrix for value in row]
        flat_b = [value for row in b.cd_matrix for value in row]
        if any(abs(x - y) > tolerance for x, y in zip(flat_a, flat_b, strict=True)):
            return False
    return True


def is_within_bounds(point: PixelCoordinate, width: int, height: int) -> bool:
    """Whether `point` falls within an image frame of `width` x `height`.

    Deliberately separate from coordinate transformation: a WCS solution
    can be mathematically valid far outside the pixel grid it was solved
    for, so boundedness is a distinct question. Uses the pixel-centre
    convention, where pixel index ``0`` spans ``[-0.5, 0.5)``.
    """
    return -0.5 <= point.x <= width - 0.5 and -0.5 <= point.y <= height - 0.5


@dataclass(frozen=True)
class FrameResolution:
    """The raw and Astropy-inferred celestial reference frame of a WCS.

    `header_radesys` is frequently absent from Astrometry.net output; when
    it is, Astropy infers a default frame from `header_equinox` alone
    (e.g. FK5 for equinox 2000). This is recorded explicitly so a solution
    is never silently labelled ICRS without justification.
    """

    header_radesys: str | None
    header_equinox: float | None
    frame_name: str
    frame_equinox: float | None

    def to_dict(self) -> dict:
        return {
            "header_radesys": self.header_radesys,
            "header_equinox": self.header_equinox,
            "frame_name": self.frame_name,
            "frame_equinox": self.frame_equinox,
        }


def resolve_celestial_frame(
    wcs: WCS, wcs_summary: WcsSummary
) -> tuple[BaseCoordinateFrame, FrameResolution]:
    """Resolve a WCS's celestial reference frame using Astropy's WCS machinery.

    Returns both the live Astropy frame instance (for use in an actual
    coordinate transform) and a JSON-serializable summary of the raw and
    inferred frame metadata. `wcs_summary` supplies the *raw* header
    ``RADESYS``/``EQUINOX`` (which may be absent), since Astropy's own
    `wcs.wcs.radesys` already substitutes its inferred default and cannot
    be used to detect absence.

    Raises
    ------
    NonCelestialWcsError
        If the WCS has no celestial axes.
    FrameResolutionError
        If Astropy cannot resolve a celestial frame from the WCS.
    """
    if not wcs.has_celestial:
        raise NonCelestialWcsError("WCS solution has no celestial axes.")
    try:
        frame = wcs_to_celestial_frame(wcs)
    except ValueError as exc:
        raise FrameResolutionError(
            f"Could not resolve a celestial frame from the WCS: {exc}"
        ) from exc

    frame_equinox = getattr(frame, "equinox", None)
    resolution = FrameResolution(
        header_radesys=wcs_summary.header_radesys,
        header_equinox=wcs_summary.equinox,
        frame_name=frame.name,
        frame_equinox=(
            float(frame_equinox.jyear) if frame_equinox is not None else None
        ),
    )
    return frame, resolution


def frame_coordinate_to_icrs(
    ra_deg: float, dec_deg: float, frame: BaseCoordinateFrame
) -> CelestialCoordinate:
    """Explicitly transform a coordinate expressed in `frame` into ICRS.

    `frame` should be the live Astropy frame returned by
    `resolve_celestial_frame`; this performs an actual frame
    transformation (e.g. FK5(J2000) -> ICRS), not a relabelling.
    """
    sky = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame=frame)
    icrs = sky.transform_to("icrs")
    return CelestialCoordinate(ra_deg=float(icrs.ra.deg), dec_deg=float(icrs.dec.deg))
