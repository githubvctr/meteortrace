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
