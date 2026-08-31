"""Unit tests for `meteortrace.geometry`.

These tests validate scientific behaviour (angular relationships, ordering
conventions, degeneracy handling) rather than private implementation
details.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from meteortrace.contracts import CelestialCoordinate, ObservedTrail, ShowerRadiant
from meteortrace.geometry import (
    RadiantAlignment,
    angular_separation_deg,
    classify_radiant_alignment,
    closest_point_on_great_circle,
    great_circle_normal,
    radiant_cross_track_separation_deg,
    signed_along_track_angle_deg,
    to_unit_vector,
    trail_angular_length_deg,
)

# Preliminary reference case (see task description / README): a trail
# spanning two rounded RA/Dec endpoints and a provisional Perseid radiant.
REFERENCE_START = CelestialCoordinate(ra_deg=331.81, dec_deg=55.02)
REFERENCE_END = CelestialCoordinate(ra_deg=309.93, dec_deg=42.20)
REFERENCE_RADIANT = ShowerRadiant(
    name="Perseids (provisional)",
    coordinate=CelestialCoordinate(ra_deg=48.0, dec_deg=58.0),
)


def test_reference_trail_angular_length() -> None:
    trail = ObservedTrail(REFERENCE_START, REFERENCE_END)
    assert trail_angular_length_deg(trail) == pytest.approx(19.1820, abs=1e-3)


def test_reference_cross_track_separation() -> None:
    trail = ObservedTrail(REFERENCE_START, REFERENCE_END)
    separation = radiant_cross_track_separation_deg(trail, REFERENCE_RADIANT)
    assert separation == pytest.approx(2.4285, abs=1e-3)


def test_reference_closest_point() -> None:
    trail = ObservedTrail(REFERENCE_START, REFERENCE_END)
    closest = closest_point_on_great_circle(trail, REFERENCE_RADIANT)
    assert closest.ra_deg == pytest.approx(45.6607, abs=1e-3)
    assert closest.dec_deg == pytest.approx(55.9328, abs=1e-3)


def test_reference_signed_along_track_position() -> None:
    trail = ObservedTrail(REFERENCE_START, REFERENCE_END)
    closest = closest_point_on_great_circle(trail, REFERENCE_RADIANT)
    along_track = signed_along_track_angle_deg(trail, closest)
    assert along_track == pytest.approx(-39.82, abs=0.05)


def test_reference_radiant_is_on_backward_extension() -> None:
    trail = ObservedTrail(REFERENCE_START, REFERENCE_END)
    assert classify_radiant_alignment(trail, REFERENCE_RADIANT) is (
        RadiantAlignment.BACKWARD_EXTENSION
    )


def test_endpoint_separation_matches_independent_astropy_check() -> None:
    ours = angular_separation_deg(REFERENCE_START, REFERENCE_END)
    astropy_start = SkyCoord(
        ra=REFERENCE_START.ra_deg * u.deg, dec=REFERENCE_START.dec_deg * u.deg
    )
    astropy_end = SkyCoord(
        ra=REFERENCE_END.ra_deg * u.deg, dec=REFERENCE_END.dec_deg * u.deg
    )
    astropy_separation = astropy_start.separation(astropy_end).deg
    assert ours == pytest.approx(astropy_separation, abs=1e-9)


def test_right_ascension_normalizes_across_360_boundary() -> None:
    coordinate = CelestialCoordinate(ra_deg=-10.0, dec_deg=0.0)
    assert coordinate.ra_deg == pytest.approx(350.0)

    coordinate = CelestialCoordinate(ra_deg=370.0, dec_deg=0.0)
    assert coordinate.ra_deg == pytest.approx(10.0)


def test_identical_coordinates_have_zero_separation() -> None:
    a = CelestialCoordinate(ra_deg=123.4, dec_deg=-12.3)
    b = CelestialCoordinate(ra_deg=123.4, dec_deg=-12.3)
    assert angular_separation_deg(a, b) == pytest.approx(0.0, abs=1e-9)


def test_orthogonal_coordinates_have_90_degree_separation() -> None:
    # (RA=0, Dec=0) and (RA=90, Dec=0) point along orthogonal cardinal axes.
    a = CelestialCoordinate(ra_deg=0.0, dec_deg=0.0)
    b = CelestialCoordinate(ra_deg=90.0, dec_deg=0.0)
    assert angular_separation_deg(a, b) == pytest.approx(90.0, abs=1e-9)


def test_equatorial_great_circle_matches_analytic_case() -> None:
    # A trail entirely on the celestial equator defines the equatorial
    # great circle, whose normal must point along +/- the polar axis.
    start = CelestialCoordinate(ra_deg=0.0, dec_deg=0.0)
    end = CelestialCoordinate(ra_deg=90.0, dec_deg=0.0)
    trail = ObservedTrail(start, end)
    normal = great_circle_normal(trail)
    assert normal == pytest.approx(np.array([0.0, 0.0, 1.0]), abs=1e-9)

    radiant = ShowerRadiant(
        name="pole", coordinate=CelestialCoordinate(ra_deg=200.0, dec_deg=90.0)
    )
    assert radiant_cross_track_separation_deg(trail, radiant) == pytest.approx(
        90.0, abs=1e-9
    )


def test_radiant_exactly_on_backward_extension() -> None:
    # A trail along the equator from RA=10 to RA=30; a radiant at RA=350
    # lies exactly on the equatorial great circle, before the start.
    start = CelestialCoordinate(ra_deg=10.0, dec_deg=0.0)
    end = CelestialCoordinate(ra_deg=30.0, dec_deg=0.0)
    trail = ObservedTrail(start, end)
    radiant = ShowerRadiant(
        name="behind-start", coordinate=CelestialCoordinate(ra_deg=350.0, dec_deg=0.0)
    )
    assert (
        classify_radiant_alignment(trail, radiant)
        is RadiantAlignment.BACKWARD_EXTENSION
    )


def test_radiant_exactly_on_forward_extension() -> None:
    # Same trail; a radiant at RA=60 lies exactly on the great circle,
    # beyond the end.
    start = CelestialCoordinate(ra_deg=10.0, dec_deg=0.0)
    end = CelestialCoordinate(ra_deg=30.0, dec_deg=0.0)
    trail = ObservedTrail(start, end)
    radiant = ShowerRadiant(
        name="beyond-end", coordinate=CelestialCoordinate(ra_deg=60.0, dec_deg=0.0)
    )
    assert (
        classify_radiant_alignment(trail, radiant) is RadiantAlignment.FORWARD_EXTENSION
    )


def test_declination_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        CelestialCoordinate(ra_deg=10.0, dec_deg=90.5)
    with pytest.raises(ValueError):
        CelestialCoordinate(ra_deg=10.0, dec_deg=-91.0)


def test_non_finite_coordinate_values_raise() -> None:
    with pytest.raises(ValueError):
        CelestialCoordinate(ra_deg=math.nan, dec_deg=0.0)
    with pytest.raises(ValueError):
        CelestialCoordinate(ra_deg=math.inf, dec_deg=0.0)
    with pytest.raises(ValueError):
        CelestialCoordinate(ra_deg=10.0, dec_deg=math.nan)


def test_coincident_endpoints_are_rejected() -> None:
    point = CelestialCoordinate(ra_deg=45.0, dec_deg=10.0)
    trail = ObservedTrail(point, point)
    with pytest.raises(ValueError):
        great_circle_normal(trail)


def test_effectively_antipodal_endpoints_are_rejected() -> None:
    start = CelestialCoordinate(ra_deg=45.0, dec_deg=10.0)
    # Exactly antipodal up to floating-point rounding.
    end = CelestialCoordinate(ra_deg=45.0 + 180.0, dec_deg=-10.0)
    trail = ObservedTrail(start, end)
    with pytest.raises(ValueError):
        great_circle_normal(trail)


def test_unit_vectors_have_unit_norm() -> None:
    for ra, dec in [(0.0, 0.0), (359.999, 89.999), (180.0, -89.999), (270.0, 0.0)]:
        vector = to_unit_vector(CelestialCoordinate(ra_deg=ra, dec_deg=dec))
        assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-12)


def test_outputs_remain_finite_for_near_boundary_inputs() -> None:
    # Near a pole and near the RA wrap-around, but well away from the
    # coincident/antipodal degeneracies handled separately above.
    start = CelestialCoordinate(ra_deg=0.001, dec_deg=89.999)
    end = CelestialCoordinate(ra_deg=90.0, dec_deg=0.001)
    trail = ObservedTrail(start, end)
    radiant = ShowerRadiant(
        name="near-boundary",
        coordinate=CelestialCoordinate(ra_deg=359.999, dec_deg=-89.999),
    )

    assert math.isfinite(trail_angular_length_deg(trail))
    assert math.isfinite(radiant_cross_track_separation_deg(trail, radiant))
    closest = closest_point_on_great_circle(trail, radiant)
    assert math.isfinite(closest.ra_deg)
    assert math.isfinite(closest.dec_deg)
    assert math.isfinite(signed_along_track_angle_deg(trail, closest))
