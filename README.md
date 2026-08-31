# MeteorTrace

A compact, reproducible Python tool for analysing meteors photographed
with consumer cameras, starting from explicit pixel coordinates through
astrometry, trajectory, and shower-radiant comparison.

## Status

**Early development.** Only the spherical-geometry foundation described
below is implemented and tested. The pixel-coordinate transformation and
WCS astrometry pipeline that would turn a real photograph into a
`CelestialCoordinate` trail do not exist yet. Nothing in this repository
has processed a real image.

## Scientific inference chain

MeteorTrace is designed around one inference chain, built incrementally:

```
processed image pixels
  -> explicit pixel-coordinate transformation
  -> WCS astrometry
  -> celestial trajectory
  -> shower-radiant comparison
  -> processed-image brightness/colour proxies
  -> uncertainty
  -> constrained interpretation
```

This repository currently implements the trajectory and shower-radiant
comparison stages in isolation, as pure spherical geometry, so that they
can be tested independently of any imaging pipeline.

## What can and cannot be inferred from one consumer-camera image

**Can**, once the full pipeline exists: an astrometric trajectory (a great
circle on the sky), its angular length, and whether that great circle is
geometrically consistent with a candidate shower radiant.

**Cannot**, from a single still image, regardless of pipeline
completeness: true 3D trajectory, speed, altitude, physical
fragmentation, calibrated photometry, spectroscopy, or confirmed shower
membership. Those require multi-station triangulation, timing, and/or
orbital data outside this project's scope.

## Preliminary geometry example

The numbers below are an independently reproduced reference calculation
using rounded, illustrative RA/Dec values — **not** a result derived from
an original photograph via this repository's (not yet implemented) WCS
pipeline. They exist to document and test the geometry API.

```python
from meteortrace import (
    CelestialCoordinate, ObservedTrail, ShowerRadiant,
    trail_angular_length_deg, radiant_cross_track_separation_deg,
    closest_point_on_great_circle, signed_along_track_angle_deg,
    classify_radiant_alignment,
)

trail = ObservedTrail(
    start=CelestialCoordinate(ra_deg=331.81, dec_deg=55.02),
    end=CelestialCoordinate(ra_deg=309.93, dec_deg=42.20),
)
radiant = ShowerRadiant(
    name="Perseids (provisional)",
    coordinate=CelestialCoordinate(ra_deg=48.0, dec_deg=58.0),
)

trail_angular_length_deg(trail)                        # ~19.18 deg
radiant_cross_track_separation_deg(trail, radiant)     # ~2.43 deg
closest_point_on_great_circle(trail, radiant)          # RA ~45.66, Dec ~+55.93
signed_along_track_angle_deg(trail, ...)                # ~-39.82 deg from start
classify_radiant_alignment(trail, radiant)             # RadiantAlignment.BACKWARD_EXTENSION
```

A ~2.4° cross-track separation and a radiant falling on the trail's
backward extension are **geometrically consistent with the Perseids** —
not a confirmed Perseid detection. See below.

## Geometric consistency vs. confirmed membership

`classify_radiant_alignment` and `radiant_cross_track_separation_deg`
report how closely a trail's great circle aligns with a candidate
radiant, and whether that alignment falls on the physically expected
backward extension. This is necessary but not sufficient for shower
membership: confirming membership requires velocity, timing, and orbital
information that a single geometric comparison cannot provide.

## Architecture

- `meteortrace.contracts` — immutable, validated dataclasses
  (`CelestialCoordinate`, `ObservedTrail`, `ShowerRadiant`) that enforce
  scientific invariants (finite values, declination range, RA
  normalization) at construction time.
- `meteortrace.geometry` — pure, deterministic functions operating on unit
  vectors: angular separation, great-circle construction, cross-track and
  along-track comparisons against a radiant. No hidden state, no silent
  fallback results.

Full conventions (units, orientation, numerical degeneracies) are
documented in [docs/coordinate_conventions.md](docs/coordinate_conventions.md).

## Installation and tests

Requires Python 3.12 and [Poetry](https://python-poetry.org/) 2.4+.

```bash
poetry install
poetry run pytest
```

## Repository map

```
src/meteortrace/       geometry package (contracts.py, geometry.py)
tests/unit/            unit tests
docs/                  coordinate conventions and (future) figures
data/                  data-handling policy; no imagery is committed
```

## Reproducibility and uncertainty

- All geometric functions are deterministic: identical inputs always
  produce identical outputs, with no hidden state or caching.
- Degenerate inputs (coincident or effectively antipodal trail endpoints,
  non-finite coordinates, out-of-range declinations) raise explicit
  exceptions rather than returning a plausible-looking fallback value.
- Numerical tolerances (e.g. for degeneracy detection) are documented in
  [docs/coordinate_conventions.md](docs/coordinate_conventions.md) rather
  than left implicit.
- Formal propagated uncertainty (e.g. Monte Carlo over astrometric
  solutions) is not implemented yet; see Roadmap.

## Roadmap

1. Explicit pixel-coordinate transformation and WCS astrometry, so that
   `ObservedTrail` instances can be derived from real photographs instead
   of hand-entered coordinates.
2. Brightness and colour proxies from processed image pixels.
3. Monte Carlo uncertainty propagation through the full chain.
4. Report generation.

## License and citation

MIT License — see [LICENSE](LICENSE).

Citation metadata is provided in [CITATION.cff](CITATION.cff).
