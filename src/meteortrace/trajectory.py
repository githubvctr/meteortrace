"""Importable pixel-to-trajectory analysis pipeline.

Combines WCS ingestion, explicit frame-to-ICRS conversion, the existing
spherical-geometry layer, and repeated-selection Monte Carlo uncertainty
into one mean result plus a selection-only uncertainty summary. WCS
residual diagnostics and the provisional-radiant model are recorded
alongside the geometry, never folded into it numerically.
"""

from __future__ import annotations

from dataclasses import dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.coordinates.baseframe import BaseCoordinateFrame
from astropy.wcs import WCS

from meteortrace.astrometry import frame_coordinate_to_icrs, pixel_to_sky
from meteortrace.contracts import CelestialCoordinate, ObservedTrail, ShowerRadiant
from meteortrace.geometry import (
    RadiantAlignment,
    classify_radiant_alignment,
    closest_point_on_great_circle,
    radiant_cross_track_separation_deg,
    signed_along_track_angle_deg,
    trail_angular_length_deg,
)
from meteortrace.pixels import PixelCoordinate
from meteortrace.uncertainty import MonteCarloSamples


@dataclass(frozen=True)
class ProvisionalRadiantModel:
    """A declared, provisional shower-radiant model input, not a confirmed truth."""

    name: str
    ra_deg: float
    dec_deg: float
    frame: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
            "frame": self.frame,
        }


def radiant_to_icrs(model: ProvisionalRadiantModel) -> ShowerRadiant:
    sky = SkyCoord(
        ra=model.ra_deg * u.deg, dec=model.dec_deg * u.deg, frame=model.frame
    )
    icrs = sky.transform_to("icrs")
    return ShowerRadiant(
        name=model.name,
        coordinate=CelestialCoordinate(
            ra_deg=float(icrs.ra.deg), dec_deg=float(icrs.dec.deg)
        ),
    )


@dataclass(frozen=True)
class MeanTrajectoryResult:
    """The deterministic trajectory result computed from mean endpoint pixels."""

    start_icrs: CelestialCoordinate
    end_icrs: CelestialCoordinate
    trail_length_deg: float
    cross_track_separation_deg: float
    closest_point_icrs: CelestialCoordinate
    along_track_deg: float
    alignment: RadiantAlignment

    def to_dict(self) -> dict:
        return {
            "start_icrs": {
                "ra_deg": self.start_icrs.ra_deg,
                "dec_deg": self.start_icrs.dec_deg,
            },
            "end_icrs": {
                "ra_deg": self.end_icrs.ra_deg,
                "dec_deg": self.end_icrs.dec_deg,
            },
            "trail_length_deg": self.trail_length_deg,
            "cross_track_separation_deg": self.cross_track_separation_deg,
            "closest_point_icrs": {
                "ra_deg": self.closest_point_icrs.ra_deg,
                "dec_deg": self.closest_point_icrs.dec_deg,
            },
            "along_track_deg": self.along_track_deg,
            "alignment": self.alignment.value,
        }


def pixel_to_icrs(
    wcs: WCS, frame: BaseCoordinateFrame, point: PixelCoordinate
) -> CelestialCoordinate:
    """Map a `WCS_SOLVED` pixel through the WCS, then explicitly into ICRS."""
    frame_coordinate = pixel_to_sky(wcs, point)
    return frame_coordinate_to_icrs(
        frame_coordinate.ra_deg, frame_coordinate.dec_deg, frame
    )


def compute_mean_trajectory(
    wcs: WCS,
    frame: BaseCoordinateFrame,
    start_pixel: PixelCoordinate,
    end_pixel: PixelCoordinate,
    radiant_model: ProvisionalRadiantModel,
) -> MeanTrajectoryResult:
    """Compute the trajectory-vs-radiant geometry for one pair of mean endpoints."""
    start_icrs = pixel_to_icrs(wcs, frame, start_pixel)
    end_icrs = pixel_to_icrs(wcs, frame, end_pixel)
    trail = ObservedTrail(start_icrs, end_icrs)
    radiant = radiant_to_icrs(radiant_model)

    closest_point = closest_point_on_great_circle(trail, radiant)
    return MeanTrajectoryResult(
        start_icrs=start_icrs,
        end_icrs=end_icrs,
        trail_length_deg=trail_angular_length_deg(trail),
        cross_track_separation_deg=radiant_cross_track_separation_deg(trail, radiant),
        closest_point_icrs=closest_point,
        along_track_deg=signed_along_track_angle_deg(trail, closest_point),
        alignment=classify_radiant_alignment(trail, radiant),
    )


@dataclass(frozen=True)
class MonteCarloSummary:
    """Selection-only uncertainty summary from repeated-selection Monte Carlo."""

    n_samples_requested: int
    n_samples_used: int
    n_excluded_degenerate: int
    trail_length_deg_median: float
    trail_length_deg_p2_5: float
    trail_length_deg_p97_5: float
    cross_track_deg_median: float
    cross_track_deg_p2_5: float
    cross_track_deg_p97_5: float
    along_track_deg_median: float
    along_track_deg_p2_5: float
    along_track_deg_p97_5: float
    alignment_fraction: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "n_samples_requested": self.n_samples_requested,
            "n_samples_used": self.n_samples_used,
            "n_excluded_degenerate": self.n_excluded_degenerate,
            "trail_length_deg_median": self.trail_length_deg_median,
            "trail_length_deg_p2_5": self.trail_length_deg_p2_5,
            "trail_length_deg_p97_5": self.trail_length_deg_p97_5,
            "cross_track_deg_median": self.cross_track_deg_median,
            "cross_track_deg_p2_5": self.cross_track_deg_p2_5,
            "cross_track_deg_p97_5": self.cross_track_deg_p97_5,
            "along_track_deg_median": self.along_track_deg_median,
            "along_track_deg_p2_5": self.along_track_deg_p2_5,
            "along_track_deg_p97_5": self.along_track_deg_p97_5,
            "alignment_fraction": self.alignment_fraction,
        }


def _batch_pixel_to_icrs(
    wcs: WCS, frame: BaseCoordinateFrame, xy: np.ndarray
) -> np.ndarray:
    """Vectorized pixel -> frame-sky -> ICRS conversion for an (n, 2) pixel array."""
    ra, dec = wcs.all_pix2world(xy[:, 0], xy[:, 1], 0)
    sky = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame=frame)
    icrs = sky.transform_to("icrs")
    return np.column_stack([icrs.ra.deg, icrs.dec.deg])


def run_monte_carlo_trajectory(
    wcs: WCS,
    frame: BaseCoordinateFrame,
    samples: MonteCarloSamples,
    radiant_model: ProvisionalRadiantModel,
) -> MonteCarloSummary:
    """Propagate repeated-selection Monte Carlo samples through the full geometry."""
    radiant = radiant_to_icrs(radiant_model)
    start_icrs_deg = _batch_pixel_to_icrs(wcs, frame, samples.start_xy)
    end_icrs_deg = _batch_pixel_to_icrs(wcs, frame, samples.end_xy)

    lengths: list[float] = []
    cross_tracks: list[float] = []
    along_tracks: list[float] = []
    alignment_counts: dict[str, int] = {status.value: 0 for status in RadiantAlignment}
    n_excluded = 0

    for i in range(samples.n_samples):
        start = CelestialCoordinate(
            ra_deg=float(start_icrs_deg[i, 0]), dec_deg=float(start_icrs_deg[i, 1])
        )
        end = CelestialCoordinate(
            ra_deg=float(end_icrs_deg[i, 0]), dec_deg=float(end_icrs_deg[i, 1])
        )
        try:
            trail = ObservedTrail(start, end)
            closest_point = closest_point_on_great_circle(trail, radiant)
            lengths.append(trail_angular_length_deg(trail))
            cross_tracks.append(radiant_cross_track_separation_deg(trail, radiant))
            along_tracks.append(signed_along_track_angle_deg(trail, closest_point))
            alignment_counts[classify_radiant_alignment(trail, radiant).value] += 1
        except ValueError:
            n_excluded += 1

    n_used = len(lengths)
    lengths_arr = np.array(lengths)
    cross_arr = np.array(cross_tracks)
    along_arr = np.array(along_tracks)

    return MonteCarloSummary(
        n_samples_requested=samples.n_samples,
        n_samples_used=n_used,
        n_excluded_degenerate=n_excluded,
        trail_length_deg_median=float(np.median(lengths_arr)),
        trail_length_deg_p2_5=float(np.percentile(lengths_arr, 2.5)),
        trail_length_deg_p97_5=float(np.percentile(lengths_arr, 97.5)),
        cross_track_deg_median=float(np.median(cross_arr)),
        cross_track_deg_p2_5=float(np.percentile(cross_arr, 2.5)),
        cross_track_deg_p97_5=float(np.percentile(cross_arr, 97.5)),
        along_track_deg_median=float(np.median(along_arr)),
        along_track_deg_p2_5=float(np.percentile(along_arr, 2.5)),
        along_track_deg_p97_5=float(np.percentile(along_arr, 97.5)),
        alignment_fraction={
            status: (count / n_used if n_used else 0.0)
            for status, count in alignment_counts.items()
        },
    )


__all__ = [
    "ProvisionalRadiantModel",
    "MeanTrajectoryResult",
    "MonteCarloSummary",
    "pixel_to_icrs",
    "radiant_to_icrs",
    "compute_mean_trajectory",
    "run_monte_carlo_trajectory",
]
