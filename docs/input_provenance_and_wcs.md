# Input Provenance, Image Orientation and WCS Ingestion

This document covers the auditable input layer added on top of the
spherical-geometry foundation described in
[coordinate_conventions.md](coordinate_conventions.md): file provenance
(`meteortrace.provenance`), pixel spaces and EXIF orientation
(`meteortrace.pixels`, `meteortrace.image`), and WCS ingestion
(`meteortrace.astrometry`), tied together by `meteortrace.audit`.

## What a WCS actually is

A World Coordinate System (WCS) solution is a mathematical mapping
between a specific pixel grid and celestial coordinates. It is not a
property of a scene, a camera, or a moment in time — it is a property of
one particular array of pixels. A WCS solved for a `4032x3024` pixel grid
describes *that* grid; it says nothing, on its own, about a different
grid, even one photographing the same sky moments later.

This matters because plate-solving services such as Astrometry.net
return a WCS tied to whatever pixel grid was actually uploaded — which
may or may not match the pixel grid of the original camera file, if the
upload path applied cropping, resizing, or rotation.

## Why a WCS belongs to a specific pixel grid

Concretely, a WCS defines a projection (e.g. `RA---TAN-SIP`) anchored at
a reference pixel (`CRPIX1`/`CRPIX2`) with a known plate scale and
orientation (the CD or PC/CDELT matrix). Every one of those quantities is
defined *in pixel units of one specific grid*. Applying the same numbers
to a differently sized, rotated, or cropped grid silently produces wrong
sky positions — the transformation still runs, and still returns
plausible-looking numbers, which is precisely what makes this class of
error dangerous. This package therefore treats "which pixel grid" as
data to be checked, not assumed.

## Pixel spaces

Three distinct pixel spaces are tracked explicitly (`meteortrace.pixels.PixelSpace`):

- `ENCODED` — the pixel grid exactly as stored/decoded from the image
  file, before any EXIF-orientation correction.
- `DISPLAY` — the orientation-normalized grid a viewer would show, after
  applying the EXIF orientation transform.
- `WCS_SOLVED` — the pixel grid a WCS solution was actually computed
  against.

A `PixelCoordinate` always carries its space as part of its identity, and
functions that consume one (e.g. `astrometry.pixel_to_sky`) reject a
coordinate from the wrong space rather than silently reinterpreting it.

## EXIF orientation

Camera files commonly store pixels in sensor (encoded) order and record
an EXIF orientation tag (1-8) describing the mirror/rotation needed to
display them correctly. `meteortrace.pixels.OrientationTransform`
implements all eight values as explicit, invertible pixel-centre mappings
(see the module for the exact per-value formulas), so that a coordinate
measured in one space can be converted to another without ambiguity.

**HEIC decoder limitation:** both real fixture images used during
development have EXIF orientation `1` (no rotation required), which makes
it impossible to empirically confirm, from these files alone, whether
`pillow-heif`/Pillow returns encoded or already-corrected dimensions when
orientation *would* require a rotation. This package does not rely on
implicit decoder correction: it always reads the orientation tag and
applies the transform explicitly, and records this limitation in every
audit's `warnings`.

## Origin and axis conventions

Consistent with the rest of the package: pixel coordinates are
zero-based, `(0, 0)` is the centre of the upper-left pixel, `x` increases
right, `y` increases down, array shapes are `(height, width)`, and pixel
points are ordered `(x, y)`. WCS pixel conversions use explicit
`origin=0` semantics (`wcs.all_pix2world(x, y, 0)`), matching this
convention rather than FITS's native 1-based pixel indexing.

## Direct solution versus transferred solution

A WCS solution is **directly valid** only for the pixel grid it was
solved against. Using it for any other grid — even one from the same
camera, the same session, or the same physical scene — is a **transfer**,
and requires independent justification: either

- a WCS solved directly on the target grid, or
- a measured pixel registration (e.g. matched stars) between the solved
  grid and the target grid.

Matching dimensions, camera model, lens, or a small time gap are
*consistent with* a transfer being valid, but do not establish it: they
are exactly the kind of evidence that looks reassuring while still being
wrong (e.g. if the target was cropped, rotated, or re-pointed).

## Two separate assessments, not one conflated status

This package deliberately reports two independent conclusions rather
than a single compatibility verdict, because they are different
scientific questions with different evidence requirements:

- **Reference-grid assessment** (`ReferenceGridStatus`) asks: does the
  WCS's solved pixel grid relate to the reference image's *own* pixel
  grid, and by what transform? `DIRECT_MATCH` requires either identical
  dimensions or a match via the file's own already-known EXIF
  orientation transform. A width/height swap that the file's own EXIF
  orientation does not explain, or a match visible only through a
  separate derived diagnostic image, is `TRANSFORM_REQUIRED`: a
  candidate relationship, not a validated one. `INCOMPATIBLE` means no
  candidate relationship was found at all; `INSUFFICIENT_EVIDENCE` means
  the reference image itself could not be read.
- **Target-transfer assessment** (`TargetTransferStatus`) asks: may this
  WCS be used for a *separately captured* target image? `DIRECT_MATCH`
  is reachable only when reference and target are proven to be the same
  file by SHA-256 hash and their pixel grids directly match — i.e. no
  transfer is actually being performed. For any two distinct files,
  matching dimensions, orientation, camera, lens, or capture time never
  produce more than `REGISTRATION_REQUIRED`: there is no bare Boolean
  "trust me" flag that can promote this to a direct match. A future
  structured registration-result contract (transformation model,
  residuals, matched points, inlier count, provenance) would be required
  to justify anything stronger, and is not implemented here.

A dimension match is always evidence about *what transform might
apply*, never proof of *which* transform: rotation direction, mirroring,
cropping and resampling are not distinguishable from width and height
alone.

## Why consecutive images are not automatically aligned

Two photographs taken moments apart from a handheld or even tripod-mounted
camera are not guaranteed to share pixel geometry: manual refocus,
micro-adjustments in framing, sensor crop/orientation differences between
shots, or an intervening upload/conversion step (which may itself rotate
or resize the image) can all break pixel correspondence without changing
any EXIF metadata that would reveal it. Temporal proximity is evidence
about the *scene*, not about the *pixel grid*.

## FITS/WCS validation performed here

`meteortrace.astrometry.load_wcs` resolves the solved image's pixel
dimensions from every available source — the Astrometry.net-specific
`IMAGEW`/`IMAGEH` keywords, standard FITS `NAXIS1`/`NAXIS2`, and
Astropy's own `wcs.pixel_shape` — and raises `DimensionResolutionError`
if none are present or if they disagree, rather than silently preferring
one. It also reports, without asserting an interpretation:

- the raw header `RADESYS` (frequently absent from Astrometry.net output)
  separately from Astropy's *inferred* default frame, so that a solution
  is never silently labelled ICRS unless the header actually says so;
- SIP distortion presence and polynomial order, if present;
- the CD matrix (or PC/CDELT representation) actually stored in the
  header.

Pixel↔sky conversion and bounds checking are kept as separate concerns:
a coordinate can be validly converted far outside the pixel grid a WCS
was solved for, so `is_within_bounds` never participates in the
transformation itself.

## Privacy treatment

Audits never write absolute file paths, exact GPS coordinate values, or
raw EXIF blobs to machine-readable output. GPS presence is recorded as a
boolean only. File identity is recorded as a basename, byte size, and
SHA-256 digest. All private inputs are opened read-only; hashing streams
the file in fixed-size chunks rather than loading it whole.

## Current 9949→9950 limitation

For the 2026 Perseid session used to develop this layer: the ingested
WCS solution's pixel grid (4032×3024) is **transposed** (width and
height swapped) relative to the astrometric reference image's own
encoded grid as decoded locally (3024×4032). The reference image's own
EXIF orientation (`1`, no rotation) does not account for this swap. A
transpose is consistent with a candidate rotation (e.g. 90°) or another
derived representation, but this program has not derived or validated
rotation direction, mirroring, cropping or resampling from image
content — reference-grid assessment: `TRANSFORM_REQUIRED`, not an
established match.

The fireball image (`IMG_9950`) is a confirmed-distinct file from the
reference by SHA-256 hash. Their recorded `DateTimeOriginal` values
(with explicit `OffsetTimeOriginal` of `+02:00` on both files) are 34.0
seconds apart, with the reference recorded before the target. Shared
camera, lens and orientation metadata, and this timestamp proximity, are
consistent with the two images belonging to the same session, but do
not establish shared pixel geometry — target-transfer assessment:
`REGISTRATION_REQUIRED`. Transferring this WCS to `IMG_9950` requires
either a measured registration between the two images or a WCS solved
directly on `IMG_9950`; neither is implemented in this repository yet.
