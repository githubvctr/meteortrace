"""Validated data contracts for spherical-sky geometry.

These dataclasses enforce the invariants that must hold before any
downstream geometric calculation is attempted. They intentionally contain
no trigonometry; all vector math lives in :mod:`meteortrace.geometry`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CelestialCoordinate:
    """An ICRS-like celestial coordinate.

    Parameters
    ----------
    ra_deg : float
        Right ascension in degrees. Normalized to ``[0, 360)`` on construction.
    dec_deg : float
        Declination in degrees. Must lie in ``[-90, 90]``.

    Raises
    ------
    ValueError
        If either value is non-finite, or if `dec_deg` lies outside
        ``[-90, 90]``.
    """

    ra_deg: float
    dec_deg: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.ra_deg) or not math.isfinite(self.dec_deg):
            raise ValueError(
                "ra_deg and dec_deg must be finite, got "
                f"ra_deg={self.ra_deg}, dec_deg={self.dec_deg}."
            )
        if not (-90.0 <= self.dec_deg <= 90.0):
            raise ValueError(f"dec_deg must lie in [-90, 90], got {self.dec_deg}.")
        # Right ascension is an angle on a circle: normalize rather than reject.
        object.__setattr__(self, "ra_deg", self.ra_deg % 360.0)


@dataclass(frozen=True)
class ObservedTrail:
    """An observed meteor trail, ordered from its start to its end.

    The order is significant: `start` is the visually earlier endpoint and
    `end` is the visually later endpoint. This ordering is what "forward"
    and "backward" mean elsewhere in this package.
    """

    start: CelestialCoordinate
    end: CelestialCoordinate


@dataclass(frozen=True)
class ShowerRadiant:
    """A candidate meteor shower radiant.

    Proximity of this coordinate to a trail's great circle indicates
    geometric consistency with the named shower, not confirmed membership.
    """

    name: str
    coordinate: CelestialCoordinate
