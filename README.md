# MeteorTrace

A compact, reproducible Python tool for analysing meteors photographed
with consumer cameras, starting from explicit pixel coordinates through
astrometry, trajectory, and shower-radiant comparison.

## Status

**Early development.** The spherical-geometry foundation is implemented
and tested, alongside an auditable input-provenance, image-orientation
and WCS-ingestion layer. For one real observation session, the ingested
WCS solution's pixel grid is transposed relative to the astrometric
reference image's own decoded grid — a candidate rotation, not a
validated one — so the reference-grid relationship is not yet
established. Transferring the WCS to the separately captured fireball
image requires either a measured registration or an independent WCS
solved directly on that image. No real fireball trajectory has been
produced yet: end-to-end pixel-to-sky extraction from the fireball image
is not implemented.

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
completeness: true 3D trajectory, altitude, physical fragmentation,
calibrated photometry, or spectroscopy. Those require multi-station
triangulation and/or orbital data outside this project's scope.

**Speed** is not one question but two. Apparent angular rate (degrees
per second across the sky) can be estimated from a single image if
exposure timing is trustworthy; physical, linear speed additionally
requires range to the meteor (from triangulation or an assumed altitude)
or other independent geometry, and cannot come from angular measurements
alone.

**Shower membership** is not an all-or-nothing orbital question either.
Activity date, radiant dispersion, and angular velocity consistent with
a known shower can strengthen a probabilistic classification even from
single-station geometry. Trajectory and orbital information (typically
requiring multi-station data) provide substantially stronger evidence,
but their absence does not make single-image classification meaningless
— only weaker.

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

closest_point = closest_point_on_great_circle(trail, radiant)

trail_angular_length_deg(trail)                          # ~19.18 deg
radiant_cross_track_separation_deg(trail, radiant)       # ~2.43 deg
closest_point                                            # RA ~45.66, Dec ~+55.93
signed_along_track_angle_deg(trail, closest_point)       # ~-39.82 deg from start
classify_radiant_alignment(trail, radiant)               # RadiantAlignment.BACKWARD_EXTENSION
```

A ~2.4° cross-track separation and a radiant falling on the trail's
backward extension are **geometrically consistent with the Perseids** —
not a confirmed Perseid detection. See below.

## Geometric consistency vs. confirmed membership

`classify_radiant_alignment` and `radiant_cross_track_separation_deg`
report how closely a trail's great circle aligns with a candidate
radiant, and whether that alignment falls on the physically expected
backward extension. This is necessary but not sufficient for shower
membership: activity date, radiant dispersion, and angular velocity can
strengthen a probabilistic classification, while trajectory and orbital
information (typically from multi-station data) provide substantially
stronger evidence than single-image geometry alone can.

## Architecture

- `meteortrace.contracts` — immutable, validated dataclasses
  (`CelestialCoordinate`, `ObservedTrail`, `ShowerRadiant`) that enforce
  scientific invariants (finite values, declination range, RA
  normalization) at construction time.
- `meteortrace.geometry` — pure, deterministic functions operating on unit
  vectors: angular separation, great-circle construction, cross-track and
  along-track comparisons against a radiant. No hidden state, no silent
  fallback results.
- `meteortrace.provenance` — streaming SHA-256 file hashing and
  machine-readable, path-free provenance records.
- `meteortrace.pixels` — explicit pixel-space identity (encoded, display,
  WCS-solved) and the eight EXIF-orientation transforms between them.
- `meteortrace.image` — read-only HEIC/JPEG metadata extraction,
  distinguishing encoded and orientation-normalized dimensions; GPS
  presence is recorded as a boolean only.
- `meteortrace.astrometry` — read-only Astrometry.net WCS/FITS ingestion,
  pixel↔sky conversion with explicit `origin=0` semantics, and dimension
  resolution that fails loudly on disagreement rather than guessing.
- `meteortrace.audit` — orchestrates the above into two separate,
  evidence-based assessments: whether a WCS solution relates to its own
  reference image (`ReferenceGridStatus`), and whether it may be
  transferred to a separately captured target image
  (`TargetTransferStatus`).

Full conventions (units, orientation, numerical degeneracies, pixel
spaces, WCS ingestion) are documented in
[docs/coordinate_conventions.md](docs/coordinate_conventions.md) and
[docs/input_provenance_and_wcs.md](docs/input_provenance_and_wcs.md).

## Installation and tests

Requires Python 3.12 and [Poetry](https://python-poetry.org/) 2.4+.

```bash
poetry install
poetry run pytest
```

Auditing a set of real inputs (never committed; see `data/README.md`):

```bash
poetry run meteortrace audit-inputs \
  --reference-image data/private/.../reference.HEIC \
  --target-image data/private/.../target.HEIC \
  --wcs data/private/.../solution.fits \
  --output results/.../input_audit.json
```

## Repository map

```
src/meteortrace/       geometry, contracts, provenance, pixel/image/WCS ingestion, CLI
tests/unit/            unit tests
tests/integration/     CLI/integration tests
docs/                  coordinate conventions, input-provenance/WCS notes, (future) figures
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

1. Measured image registration (or an independently solved WCS) so that
   this WCS layer can be applied to a target image safely, and automated
   pixel-trail extraction so that `ObservedTrail` instances can be
   derived from real photographs instead of hand-entered coordinates.
2. Brightness and colour proxies from processed image pixels.
3. Monte Carlo uncertainty propagation through the full chain.
4. Report generation.

## License and citation

MIT License — see [LICENSE](LICENSE).

Citation metadata is provided in [CITATION.cff](CITATION.cff).
