## TASK_001 — Geometry foundation

**Objective:** Establish validated spherical geometry independently of image processing.

**Delivered:** Typed coordinate contracts, great-circle calculations, radiant comparison, tests, CI and initial documentation.

**Validation:** 18 tests passed; Black, Ruff, pre-commit and package build passed.

**Key decisions:**
- Ordered trails encode observed motion.
- Proximity and directional consistency remain separate.
- Degenerate great circles fail explicitly.

**Remaining limitations:** No pixel/WCS ingestion or propagated uncertainty.

## TASK_002 — Input provenance, orientation and WCS ingestion

**Objective:** Build an auditable layer to determine whether an ingested
Astrometry.net WCS solution can safely be applied to a real fireball
photograph, without calculating a trajectory or performing registration.

**Delivered:** `provenance.py` (streaming SHA-256 file records),
`pixels.py` (explicit pixel-space identity and all eight EXIF-orientation
transforms), `image.py` (read-only HEIC/JPEG metadata, GPS presence as a
boolean only), `astrometry.py` (read-only WCS/FITS ingestion, dimension
resolution across IMAGEW/IMAGEH/NAXIS/pixel_shape, pixel↔sky conversion
with explicit `origin=0`), `audit.py` (two explicit, separately reported
assessments — see below), and a `meteortrace audit-inputs` CLI producing
deterministic, path-free JSON under `results/`.

**Key decisions:**
- A `PixelCoordinate` always carries an explicit pixel-space identity
  (encoded/display/WCS-solved); conversion functions reject the wrong one.
- Dimension resolution fails loudly on disagreement between IMAGEW/IMAGEH,
  NAXIS1/NAXIS2, and Astropy's pixel_shape, rather than picking one.
- The raw header `RADESYS` and Astropy's inferred default frame are
  reported separately; a solution is never silently labelled ICRS.
- The audit reports two independent conclusions rather than one
  conflated status:
  - **Reference-grid assessment** (`ReferenceGridStatus`): whether the
    WCS's solved pixel grid relates to the reference image's own grid —
    `DIRECT_MATCH` (dimensions align with no transform, or with the
    file's own established EXIF-orientation transform), `TRANSFORM_REQUIRED`
    (dimensions match only after an unvalidated hypothetical transform,
    e.g. a width/height swap not explained by the file's own EXIF
    orientation, or a match only via a separate derived diagnostic
    image), `INCOMPATIBLE`, or `INSUFFICIENT_EVIDENCE`.
  - **Target-transfer assessment** (`TargetTransferStatus`): whether the
    WCS may be used for a *separately captured* target image —
    `DIRECT_MATCH`, `REGISTRATION_REQUIRED`, `INCOMPATIBLE`, or
    `INSUFFICIENT_EVIDENCE`.
- `TargetTransferStatus.DIRECT_MATCH` is reachable only when reference
  and target are proven to be the same file by SHA-256 hash *and* their
  encoded pixel grids directly match. There is no Boolean escape hatch:
  matching dimensions or metadata on two distinct files always yields
  `REGISTRATION_REQUIRED`. A future structured registration-result
  contract (transformation model, residuals, matched points, inlier
  count, provenance) would be required to justify anything stronger, and
  is not implemented.
- A dimension match is treated strictly as evidence for a *candidate*
  transform, never proof of *which* transform (rotation direction,
  mirroring, cropping, resampling are not distinguishable from
  width/height alone).

**Real audit conclusion (non-sensitive, corrected):** the WCS solution's
pixel grid (4032×3024) is transposed (width/height swapped) relative to
the astrometric reference image's own encoded grid as decoded locally
(3024×4032). The reference image's own EXIF orientation (`1`, no
rotation) does not account for this swap, so the specific transform
(rotation direction, mirroring, cropping) is **not established** by this
program — reference-grid assessment: `TRANSFORM_REQUIRED`. The fireball
image is a confirmed-distinct file by hash, shares camera/lens/orientation
metadata with the reference; their recorded `DateTimeOriginal` +
`OffsetTimeOriginal` timestamps (both `+02:00`) are 34.0 s apart, with the
reference recorded *before* the target. None of this constitutes a
structured, measured pixel registration, so target-transfer assessment:
`REGISTRATION_REQUIRED`.

**Validation:** 83 tests passed (18 pre-existing geometry tests
unchanged, 65 new); coverage 97% overall, all new modules ≥91%
(`audit.py` 100%). Real audit re-run against the actual 2026 Perseid
session inputs; all five private-file SHA-256 hashes confirmed unchanged
before and after.

**Remaining limitation:** the WCS has not been shown valid for the
fireball image itself; no trajectory has been computed from it, and
image registration is not implemented. The explicit reference-grid
transform (candidate 90° rotation or otherwise) remains a hypothesis to
be validated from image content in a future task.

**Correction note:** an earlier version of this entry stated the WCS
grid "matches" the reference image "once transposed" and described the
overall conclusion as a single `TARGET_REGISTRATION_REQUIRED` status.
That conflated two distinct questions (does the WCS relate to its own
reference image, and can it be transferred to a different target image)
and overstated the reference-grid relationship as established rather
than hypothesised. It also exposed a bare `registration_evidence`
Boolean capable of producing a direct-match conclusion without
structured evidence. Both are corrected above; no trajectory, image
content comparison, or registration was implemented as part of the fix.
