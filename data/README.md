# Data directory

This directory holds example data and documentation for local analysis. It
does not contain original meteor imagery or private observation files.

## Layout

- `data/private/` — original photographs, Astrometry.net solutions, and any
  other source material tied to a real observation. **Always ignored by
  git** (see `.gitignore`). Files here must remain byte-for-byte unmodified;
  MeteorTrace should read them, never rewrite them in place.
- `data/raw/` — any other unprocessed input data. Also always ignored.
- Selected, deliberately public example files (small, synthetic, or
  explicitly cleared for release) may be committed outside `private/` and
  `raw/`.

Within `data/private/`, a single observation session typically contains
several distinct roles that must not be conflated:

- **Fireball target image** — the photograph actually containing the
  meteor. This is the image the trajectory must ultimately be extracted
  from.
- **Astrometric reference image** — a separate photograph (e.g. taken
  immediately before or after the target, from a fixed tripod) that was
  submitted to a plate-solving service to obtain a WCS solution. Temporal
  or positional proximity to the target does not imply pixel alignment.
- **Derived Astrometry.net products** — the WCS/FITS solution itself, plus
  any diagnostic/annotated images the solver produced. These describe the
  *reference* image's pixel grid, not necessarily the target's.
- **Other session images** — anything else captured around the same time
  that is not directly used in the trajectory calculation.

Every separately pointed or time-separated image generally requires its
own WCS solution, or a measured registration against an image that has
one. A shared timestamp, camera, or lens does not establish shared pixel
geometry; see [docs/input_provenance_and_wcs.md](../docs/input_provenance_and_wcs.md).

## Provenance

No private file should ever be committed just to make an example runnable.
Once a real observation is used, its provenance should be recorded through
a content hash and a manifest entry (file name, capture metadata, and the
processing steps applied), rather than by committing the source file
itself.

## Public previews

A derived, metadata-stripped preview image (with GPS/EXIF/location data
removed and reviewed before release) may later be placed under
`docs/assets/` for documentation purposes. No such preview exists yet.
