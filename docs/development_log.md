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

## TASK_003 — Manual selection and trajectory analysis

**Objective:** Validate a *direct* WCS (solved from the fireball image
itself) against its own correspondence table, and implement a manual
repeated-endpoint-selection and trajectory-analysis pipeline built on it,
without inferring real endpoints or fabricating a real result.

**Delivered:** `correspondence.py` (corr.fits schema parsing, pixel-origin
determination via Astrometry.net's own field_ra/field_dec, robust
residual statistics, field coverage), frame-resolution additions to
`astrometry.py` (`resolve_celestial_frame`, `frame_coordinate_to_icrs`,
`wcs_summaries_agree`), `selection.py` (immutable, hash-tied manual
selection contract), `interactive_selection.py` (Matplotlib click
collector with a monkeypatchable seam and a non-interactive-backend
guard), `uncertainty.py` (per-endpoint covariance, deterministic seeded
Monte Carlo), `trajectory.py` + `pipeline.py` (mean and Monte
Carlo-propagated trajectory geometry against a declared provisional
radiant), `outputs.py` (analysis.json/trajectory.csv/two figures/report.md/
provenance.json), and `select-trail`/`analyze-trail` CLI commands.

**Validation:** 139 tests passed (83 pre-existing unchanged, 56 new);
coverage 96% overall, all new modules ≥85% (most ≥97%). Real WCS
validation run against the actual direct PNG/wcs.fits/corr.fits products.

**Key decisions:**
- `field_x`/`field_y`'s pixel-origin convention is established by
  reproducing Astrometry.net's own `field_ra`/`field_dec` (near-exact
  match for the correct convention, ~arcsecond-scale mismatch for the
  wrong one) rather than compared against the noisier catalogue position.
- WCS correspondence residuals are always reported as in-sample solution
  diagnostics, never as independent astrometric calibration.
- Manual selection is restricted to the `WCS_SOLVED` pixel space of the
  direct solver image only; no other pixel space is accepted.
- Repeated-selection Monte Carlo uses the full 2x2 empirical covariance
  (never assumes independent x/y) and is never combined numerically with
  WCS residuals, radiant dispersion, or frame systematics.
- A hang bug was found and fixed during testing: mocking
  `matplotlib.pyplot` via `sys.modules` alone silently fails to intercept
  `import matplotlib.pyplot as plt` once the real module has already been
  imported elsewhere (Python's `IMPORT_FROM` resolves via the parent
  package's attribute, not only `sys.modules`); fixed by patching both,
  and by adding an explicit non-interactive-backend guard plus a finite
  `ginput` timeout so a misconfigured environment fails fast instead of
  hanging indefinitely.

**Real direct-WCS validation result (non-sensitive):** the direct WCS's
pixel grid (3024×4032) matches the solver PNG's dimensions exactly — no
orientation transform or registration is needed for this pair, unlike
the transferred WCS in TASK_002. `new-image.fits`'s embedded WCS agrees
with `wcs.fits` exactly. The pixel-origin convention for `corr.fits` is
unambiguously FITS 1-based (established to ~1 microarcsecond against
Astrometry.net's own recorded positions). Field coverage is excellent
(~99% x, ~98% y). However, the 210 correspondences show a **median
angular residual of 75.0 arcsec** against their matched catalogue
positions (p68 112.2″, p95 489.5″, max 854.0″, RMS 224.4″) — anomalously
large for a typical sub-arcsecond Astrometry.net solve. This is flagged
as a warning in every validation report. RADESYS is absent from the
header (EQUINOX=2000.0 present); Astropy infers FK5(J2000), not ICRS.

**Remaining human selection gate:** because of the large internal
residuals above, this WCS's external astrometric accuracy is unverified
beyond self-consistency. No real endpoint selection was performed and no
real trajectory result exists in this repository: a human must run
`select-trail` and review the resulting `analyze-trail` report,
including its WCS-residual warning, before treating any derived
trajectory as trustworthy.
