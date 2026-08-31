# Manual Selection and Trajectory Analysis

This document covers the manual-selection and trajectory-analysis layer
added on top of the WCS-ingestion and audit layer described in
[input_provenance_and_wcs.md](input_provenance_and_wcs.md): repeated
manual endpoint clicking (`meteortrace.selection`,
`meteortrace.interactive_selection`), selection-only uncertainty
(`meteortrace.uncertainty`), WCS correspondence validation
(`meteortrace.correspondence`), and the trajectory pipeline
(`meteortrace.trajectory`, `meteortrace.pipeline`).

## Why manual selection is Version 1

Automatically detecting a meteor trail's endpoints in a photograph is a
computer-vision problem (distinguishing a faint, thin, possibly curved
streak from stars, noise, hot pixels, and compression artefacts) that is
out of scope for this version. Manual selection is scientifically
conservative: a human identifies the two endpoints, the tool repeats the
click several times to quantify how repeatable that identification is,
and every downstream number is traceable back to those specific pixel
coordinates. No endpoint is ever inferred, guessed, or hard-coded by this
package.

## Temporal ordering

The trail's start and end are a *visual, temporal* observation, not a
coordinate-derived one: the meteor is recorded moving from an earlier
position to a later one. `select-trail` always instructs the user to
click in that order — earlier (start) endpoint first, later (end)
endpoint second — for every repetition. This package never infers which
endpoint came first from RA/Dec, pixel position, or any other derived
quantity: reversing the true observed order would silently flip
"backward" and "forward" extension labels.

## Coordinate spaces

Manual selection operates entirely in the direct solver image's
`WCS_SOLVED` pixel space (see `meteortrace.pixels.PixelSpace`): the
image handed to Astrometry.net *is* the pixel grid the WCS was solved
against, so no orientation transform or grid transfer is needed or
permitted here. `ManualSelectionRecord.pixel_space` is validated to
equal `"wcs_solved"` and nothing else — this is a deliberate, temporary
restriction to the one case where no additional registration step is
required (see `docs/input_provenance_and_wcs.md` for why a transfer to a
different pixel grid cannot be assumed valid).

## Direct-WCS relationship

Only the **direct** WCS (solved from a metadata-stripped PNG rendering of
the fireball image itself) is used for trajectory analysis, not the
HEIC-derived or reference-image solutions from TASK_002, which remain
secondary cross-check evidence. `meteortrace.correspondence` validates
this direct WCS against its own Astrometry.net correspondence table
(`corr.fits`) before any trajectory number is computed.

## Repeated-selection uncertainty

For each of `start` and `end`, `meteortrace.uncertainty` computes the
sample mean, the full 2x2 covariance matrix (not assumed diagonal — a
human's hand or eye movement can easily correlate x and y error), and a
radial RMS spread. A deterministic, seeded parametric Monte Carlo then
draws from these two independent bivariate normals and propagates every
sample through the full spherical-geometry chain, reporting a median and
95% interval for trail length, cross-track separation, and along-track
position, plus the fraction of samples in each alignment class.

This uncertainty is explicitly scoped to **repeated-click variability
only**. It is never combined numerically with:

- WCS correspondence residuals (a separate, in-sample solution
  diagnostic — see below);
- radiant position dispersion (the provisional radiant is a single
  declared point, not a distribution, in this version);
- reference-frame systematics (the FK5/ICRS distinction is a fixed
  correction, not an uncertainty source);
- camera-specific computational-photography effects (e.g. multi-frame
  fusion possibly altering the recorded pixel position of a fast-moving
  streak) — a real, unquantified limitation that is not modelled here.

Zero or singular covariance (e.g. identical repeated clicks) is handled
explicitly: samples collapse deterministically to the mean with no
arbitrary noise invented to avoid a degenerate distribution.

## WCS residual interpretation

`meteortrace.correspondence.validate_wcs_correspondence` reports match
count, median/p68/p95/max/RMS angular residual (arcsec), field coverage,
and whether the WCS and solver-image dimensions agree — but these
residuals compare the WCS's own correspondences (the stars Astrometry.net
matched *while solving*) back against itself. They are **in-sample
solution diagnostics**: internal self-consistency evidence, not an
independent, unbiased estimate of true external astrometric accuracy
(which would require held-out reference stars never used in the fit).

The pixel-origin convention for `corr.fits`'s `field_x`/`field_y` columns
(zero-based vs FITS 1-based) is never assumed: it is determined by
actually transforming both hypotheses through the WCS and comparing
against Astrometry.net's own recorded `field_ra`/`field_dec` (which must
reproduce to floating-point precision only for the correct convention).
If neither hypothesis clearly wins, validation raises rather than
guessing.

## Frame conversion

The direct WCS's celestial frame is resolved via Astropy's
`wcs_to_celestial_frame`, exactly as in TASK_002: the raw header
`RADESYS`/`EQUINOX` are recorded separately from Astropy's inferred frame
and equinox, and every WCS-derived coordinate is explicitly transformed
into ICRS (`meteortrace.astrometry.frame_coordinate_to_icrs`) before it
is passed into the existing ICRS-like spherical-geometry layer. This is
a real coordinate transformation (via `astropy.coordinates.SkyCoord.transform_to`),
not a relabelling.

## Provisional radiant limitations

The radiant supplied to `analyze-trail` (name, RA/Dec, frame) is a
**declared model input**, recorded verbatim in every output. It is not
looked up from a catalogue and not asserted to be correct. Geometric
alignment with this radiant is evidence of consistency, never of
confirmed shower membership (see `docs/coordinate_conventions.md`).

## Commands

Collect a repeated manual selection (real clicks required; never
fabricated by this tool):

```bash
poetry run meteortrace select-trail \
  --image data/private/perseid_2026/astrometry/IMG_9950_direct/submitted/IMG_9950_display_solver.png \
  --wcs data/private/perseid_2026/astrometry/IMG_9950_direct/downloads/wcs.fits \
  --repeats 5 \
  --output results/perseid_2026/trail_selection.json
```

Analyse a saved selection:

```bash
poetry run meteortrace analyze-trail \
  --image data/private/perseid_2026/astrometry/IMG_9950_direct/submitted/IMG_9950_display_solver.png \
  --wcs data/private/perseid_2026/astrometry/IMG_9950_direct/downloads/wcs.fits \
  --correspondences data/private/perseid_2026/astrometry/IMG_9950_direct/downloads/corr.fits \
  --selection results/perseid_2026/trail_selection.json \
  --radiant-name "Perseids (provisional)" \
  --radiant-ra-deg 48.0 --radiant-dec-deg 58.0 --radiant-frame icrs \
  --samples 10000 --seed 20260812 \
  --output-dir results/perseid_2026/analysis
```

## Output meanings

- `analysis.json` — the complete machine-readable result: inputs and
  hashes, resolved frames, the mean-endpoint result, selection-only
  uncertainty, WCS validation diagnostics, and the declared radiant
  model.
- `trajectory.csv` — an ordered, sampled great-circle path (RA/Dec, ICRS,
  degrees) from the mean start to the mean end, for plotting.
- `image_overlay.png` — the solver image with every repeated click, the
  mean endpoints, the observed direction arrow, and 1-sigma uncertainty
  ellipses; explicitly labelled as manual selection, not automated
  detection.
- `radiant_geometry.png` — the observed segment, its backward extension,
  the provisional radiant, and the closest great-circle point, in
  RA/Dec; explicitly labelled as a consistency check, not confirmation.
- `report.md` — a human-readable summary separating observations, model
  inputs, selection-only uncertainty, WCS internal residuals, the
  supported conclusion, and explicitly unsupported interpretations.
- `provenance.json` — file identities/hashes, the run's configuration
  (samples, seed, radiant model), and package version, with no private
  paths.
