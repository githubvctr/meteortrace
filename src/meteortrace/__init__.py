"""MeteorTrace: reproducible analysis of meteors photographed with consumer cameras.

This version implements the spherical-geometry foundation (validated
celestial coordinates, ordered observed trails, great-circle comparisons
against candidate shower radiants) plus an auditable input-provenance,
image-orientation and WCS-ingestion layer (`meteortrace.provenance`,
`meteortrace.image`, `meteortrace.pixels`, `meteortrace.astrometry`,
`meteortrace.audit`). The latter are imported directly from their
modules rather than re-exported here, so that `import meteortrace` stays
light and free of imaging dependencies.
"""

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

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "CelestialCoordinate",
    "ObservedTrail",
    "ShowerRadiant",
    "RadiantAlignment",
    "angular_separation_deg",
    "classify_radiant_alignment",
    "closest_point_on_great_circle",
    "great_circle_normal",
    "radiant_cross_track_separation_deg",
    "signed_along_track_angle_deg",
    "to_unit_vector",
    "trail_angular_length_deg",
]
