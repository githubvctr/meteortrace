"""Pure spherical-geometry calculations for meteor trails and shower radiants.

Angles that cross this module's public boundary as plain floats are always
expressed in degrees and named with a ``_deg`` suffix. Internally, NumPy
trigonometric functions operate on radians only; radians and degrees are
never mixed silently.
"""

from __future__ import annotations

from enum import Enum

import numpy as np

from meteortrace.contracts import CelestialCoordinate, ObservedTrail, ShowerRadiant

# Below this separation (or above 180 minus this value), a trail's endpoints
# are treated as coincident or antipodal, respectively: no unique great
# circle passes through them.
_DEGENERATE_SEPARATION_TOLERANCE_DEG = 1e-6

# Below this vector norm, a projection is treated as the zero vector for the
# purpose of recovering a celestial coordinate or a closest-point direction.
_ZERO_VECTOR_TOLERANCE = 1e-9


class RadiantAlignment(Enum):
    """Where a radiant's closest great-circle point falls relative to a trail."""

    BACKWARD_EXTENSION = "backward_extension"
    FORWARD_EXTENSION = "forward_extension"
    WITHIN_TRAIL_SPAN = "within_trail_span"


def to_unit_vector(coordinate: CelestialCoordinate) -> np.ndarray:
    """Convert a celestial coordinate to a 3D Cartesian unit vector.

    Parameters
    ----------
    coordinate : CelestialCoordinate
        Right ascension and declination in degrees.

    Returns
    -------
    numpy.ndarray
        Shape ``(3,)`` unit vector
        ``(cos(dec) cos(ra), cos(dec) sin(ra), sin(dec))``.
    """
    ra_rad = np.radians(coordinate.ra_deg)
    dec_rad = np.radians(coordinate.dec_deg)
    cos_dec = np.cos(dec_rad)
    return np.array(
        [cos_dec * np.cos(ra_rad), cos_dec * np.sin(ra_rad), np.sin(dec_rad)]
    )


def _unit_vector_to_coordinate(vector: np.ndarray) -> CelestialCoordinate:
    """Convert a (near-)unit vector back to a celestial coordinate.

    The vector is re-normalized defensively so that numerical drift
    accumulated by upstream vector arithmetic does not leak into the
    declination via `arcsin`.
    """
    norm = np.linalg.norm(vector)
    if norm < _ZERO_VECTOR_TOLERANCE:
        raise ValueError("Cannot recover a celestial coordinate from a zero vector.")
    x, y, z = vector / norm
    dec_deg = np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))
    ra_deg = np.degrees(np.arctan2(y, x)) % 360.0
    return CelestialCoordinate(ra_deg=float(ra_deg), dec_deg=float(dec_deg))


def angular_separation_deg(a: CelestialCoordinate, b: CelestialCoordinate) -> float:
    """Angular separation between two celestial coordinates, in degrees.

    Uses ``atan2(|cross|, dot)`` rather than ``arccos(dot)``: the latter
    loses precision for both very small and near-180-degree separations,
    while `atan2` remains well-conditioned across the full ``[0, 180]`` range.
    """
    va = to_unit_vector(a)
    vb = to_unit_vector(b)
    cross_norm = np.linalg.norm(np.cross(va, vb))
    dot = np.dot(va, vb)
    return float(np.degrees(np.arctan2(cross_norm, dot)))


def great_circle_normal(trail: ObservedTrail) -> np.ndarray:
    """Oriented unit normal of the great circle defined by an observed trail.

    The normal is ``start x end`` (normalized), so it encodes the observed
    start-to-end orientation rather than just the undirected great circle.

    Raises
    ------
    ValueError
        If `trail.start` and `trail.end` are too close to coincident or
        antipodal for a unique great circle to be determined.
    """
    v_start = to_unit_vector(trail.start)
    v_end = to_unit_vector(trail.end)
    cross = np.cross(v_start, v_end)
    cross_norm = np.linalg.norm(cross)
    dot = np.dot(v_start, v_end)
    separation_deg = np.degrees(np.arctan2(cross_norm, dot))
    if (
        separation_deg < _DEGENERATE_SEPARATION_TOLERANCE_DEG
        or separation_deg > 180.0 - _DEGENERATE_SEPARATION_TOLERANCE_DEG
    ):
        raise ValueError(
            "Trail endpoints are too close to coincident or antipodal "
            f"(separation={separation_deg:.3e} deg); a unique great circle "
            "cannot be constructed."
        )
    return cross / cross_norm


def trail_angular_length_deg(trail: ObservedTrail) -> float:
    """Visible angular length of an observed trail, in degrees."""
    return angular_separation_deg(trail.start, trail.end)


def radiant_cross_track_separation_deg(
    trail: ObservedTrail, radiant: ShowerRadiant
) -> float:
    """Minimum angular separation between a radiant and a trail's great circle.

    For a unit great-circle normal ``n`` and a unit radiant vector ``p``,
    ``dot(p, n)`` is the sine of the angle between ``p`` and the circle's
    plane, since that plane is everywhere perpendicular to ``n``.
    """
    normal = great_circle_normal(trail)
    v_radiant = to_unit_vector(radiant.coordinate)
    sin_cross_track = np.clip(np.dot(v_radiant, normal), -1.0, 1.0)
    return float(np.degrees(np.arcsin(np.abs(sin_cross_track))))


def closest_point_on_great_circle(
    trail: ObservedTrail, radiant: ShowerRadiant
) -> CelestialCoordinate:
    """Closest point on a trail's great circle to a candidate radiant.

    Found by projecting the radiant's unit vector onto the great-circle
    plane (removing its component along the plane's normal) and
    re-normalizing the result.

    Raises
    ------
    ValueError
        If the radiant coincides with the great circle's pole, where the
        closest point on the circle is not unique.
    """
    normal = great_circle_normal(trail)
    v_radiant = to_unit_vector(radiant.coordinate)
    projected = v_radiant - np.dot(v_radiant, normal) * normal
    if np.linalg.norm(projected) < _ZERO_VECTOR_TOLERANCE:
        raise ValueError(
            "Radiant coincides with the great circle's pole; the closest "
            "point on the circle is not unique."
        )
    return _unit_vector_to_coordinate(projected)


def signed_along_track_angle_deg(
    trail: ObservedTrail, point: CelestialCoordinate
) -> float:
    """Signed angular position of `point` along a trail's great circle.

    Zero at `trail.start`, positive toward `trail.end`. `point` need not
    lie exactly on the great circle: only its component within the
    circle's plane contributes to the result.
    """
    normal = great_circle_normal(trail)
    v_start = to_unit_vector(trail.start)
    # e1, e2 span the great-circle plane; e2 points from start toward end.
    e1 = v_start
    e2 = np.cross(normal, v_start)
    e2 = e2 / np.linalg.norm(e2)
    v_point = to_unit_vector(point)
    return float(np.degrees(np.arctan2(np.dot(v_point, e2), np.dot(v_point, e1))))


def classify_radiant_alignment(
    trail: ObservedTrail, radiant: ShowerRadiant
) -> RadiantAlignment:
    """Classify a radiant's closest great-circle point relative to a trail.

    A meteor's ordered start-to-end motion points away from its true
    radiant, so genuine shower membership is expected to place the radiant
    on the trail's backward extension (a negative along-track position).
    """
    closest_point = closest_point_on_great_circle(trail, radiant)
    along_track_deg = signed_along_track_angle_deg(trail, closest_point)
    trail_length_deg = trail_angular_length_deg(trail)
    if along_track_deg < 0.0:
        return RadiantAlignment.BACKWARD_EXTENSION
    if along_track_deg > trail_length_deg:
        return RadiantAlignment.FORWARD_EXTENSION
    return RadiantAlignment.WITHIN_TRAIL_SPAN
