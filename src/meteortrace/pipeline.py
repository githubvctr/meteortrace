"""Top-level orchestration for the `select-trail` -> `analyze-trail` workflow.

`run_trail_analysis` is the single entry point used by the `analyze-trail`
CLI and by tests; it performs no network access and never modifies its
inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import meteortrace
from meteortrace.astrometry import load_wcs, resolve_celestial_frame
from meteortrace.contracts import ObservedTrail, ShowerRadiant
from meteortrace.correspondence import load_correspondences, validate_wcs_correspondence
from meteortrace.image import read_image_metadata
from meteortrace.pixels import PixelCoordinate, PixelSpace
from meteortrace.provenance import build_file_record
from meteortrace.selection import (
    ManualSelectionRecord,
    load_selection,
    verify_selection_against_inputs,
)
from meteortrace.trajectory import (
    MeanTrajectoryResult,
    MonteCarloSummary,
    ProvisionalRadiantModel,
    compute_mean_trajectory,
    radiant_to_icrs,
    run_monte_carlo_trajectory,
)
from meteortrace.uncertainty import (
    DEFAULT_MONTE_CARLO_SEED,
    EndpointStatistics,
    MonteCarloSamples,
    compute_endpoint_statistics,
    sample_endpoints_monte_carlo,
)

ANALYSIS_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class TrailAnalysisResult:
    """Everything an output writer needs: the JSON-serializable dict plus raw pieces."""

    analysis: dict
    provenance: dict
    selection: ManualSelectionRecord
    trail_icrs: ObservedTrail
    radiant_icrs: ShowerRadiant
    mean_result: MeanTrajectoryResult
    start_stats: EndpointStatistics
    end_stats: EndpointStatistics
    monte_carlo_samples: MonteCarloSamples
    monte_carlo_summary: MonteCarloSummary


def run_trail_analysis(
    image_path: Path,
    wcs_path: Path,
    correspondences_path: Path,
    selection_path: Path,
    radiant_model: ProvisionalRadiantModel,
    n_samples: int = 10000,
    seed: int = DEFAULT_MONTE_CARLO_SEED,
) -> TrailAnalysisResult:
    """Run the complete manual-selection trajectory analysis.

    Raises
    ------
    FileNotFoundError
        If any input file does not exist.
    ValueError
        If the selection does not match the supplied image/WCS, or if the
        WCS/correspondence validation cannot be completed.
    """
    image_metadata = read_image_metadata(image_path, role="solver_image")
    image_record = build_file_record(
        image_path, role="solver_image", detected_format=image_metadata.file_format
    )
    wcs_record = build_file_record(wcs_path, role="wcs", detected_format="FITS")
    corr_record = build_file_record(
        correspondences_path, role="correspondences", detected_format="FITS"
    )
    selection_record = build_file_record(
        selection_path, role="selection", detected_format="JSON"
    )

    selection = load_selection(selection_path)
    verify_selection_against_inputs(
        selection,
        image_sha256=image_record.sha256,
        wcs_sha256=wcs_record.sha256,
        image_width=image_metadata.encoded_width,
        image_height=image_metadata.encoded_height,
    )

    wcs, wcs_summary = load_wcs(wcs_path)
    frame, frame_resolution = resolve_celestial_frame(wcs, wcs_summary)
    correspondences = load_correspondences(correspondences_path)
    wcs_validation = validate_wcs_correspondence(
        wcs,
        correspondences,
        solver_image_width=image_metadata.encoded_width,
        solver_image_height=image_metadata.encoded_height,
        wcs_width=wcs_summary.width,
        wcs_height=wcs_summary.height,
    )

    start_stats = compute_endpoint_statistics(selection.start_clicks)
    end_stats = compute_endpoint_statistics(selection.end_clicks)

    start_pixel = PixelCoordinate(
        x=start_stats.mean_x, y=start_stats.mean_y, space=PixelSpace.WCS_SOLVED
    )
    end_pixel = PixelCoordinate(
        x=end_stats.mean_x, y=end_stats.mean_y, space=PixelSpace.WCS_SOLVED
    )
    mean_result = compute_mean_trajectory(
        wcs, frame, start_pixel, end_pixel, radiant_model
    )
    trail_icrs = ObservedTrail(mean_result.start_icrs, mean_result.end_icrs)
    radiant_icrs = radiant_to_icrs(radiant_model)

    mc_samples = sample_endpoints_monte_carlo(
        start_stats, end_stats, n_samples, seed, wcs_summary.width, wcs_summary.height
    )
    mc_summary = run_monte_carlo_trajectory(wcs, frame, mc_samples, radiant_model)

    warnings: list[str] = list(wcs_validation.warnings)
    if not wcs_validation.dimensions_agree_with_solver_image:
        warnings.append(
            "Solver image and WCS dimensions disagree; treat this analysis "
            "with caution."
        )

    analysis = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "package_version": meteortrace.__version__,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            "image": image_record.to_dict(),
            "wcs": wcs_record.to_dict(),
            "correspondences": corr_record.to_dict(),
            "selection": selection_record.to_dict(),
        },
        "frame_resolution": frame_resolution.to_dict(),
        "mean_result": mean_result.to_dict(),
        "selection_uncertainty": {
            "start": start_stats.to_dict(),
            "end": end_stats.to_dict(),
            "monte_carlo": mc_summary.to_dict(),
            "seed": seed,
        },
        "wcs_validation": wcs_validation.to_dict(),
        "provisional_radiant": radiant_model.to_dict(),
        "warnings": warnings,
    }

    provenance = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "package_version": meteortrace.__version__,
        "generated_at_utc": analysis["generated_at_utc"],
        "files": [
            image_record.to_dict(),
            wcs_record.to_dict(),
            corr_record.to_dict(),
            selection_record.to_dict(),
        ],
        "configuration": {
            "n_samples": n_samples,
            "seed": seed,
            "radiant_model": radiant_model.to_dict(),
        },
    }

    return TrailAnalysisResult(
        analysis=analysis,
        provenance=provenance,
        selection=selection,
        trail_icrs=trail_icrs,
        radiant_icrs=radiant_icrs,
        mean_result=mean_result,
        start_stats=start_stats,
        end_stats=end_stats,
        monte_carlo_samples=mc_samples,
        monte_carlo_summary=mc_summary,
    )


def build_report_sections(result: TrailAnalysisResult) -> dict[str, str]:
    """Build the ordered markdown sections for `report.md`."""
    mean = result.mean_result
    mc = result.monte_carlo_summary.to_dict()
    validation = result.analysis["wcs_validation"]
    radiant = result.analysis["provisional_radiant"]
    seed = result.analysis["selection_uncertainty"]["seed"]

    observations = (
        f"An ordered trail was selected from {result.start_stats.n_repeats} "
        "repeated clicks on the earlier (start) endpoint and "
        f"{result.end_stats.n_repeats} repeated clicks on the later (end) "
        "endpoint, in the direct solver image's WCS-solved pixel space."
    )
    measurements = (
        f"Mean start: RA {mean.start_icrs.ra_deg:.4f}, "
        f"Dec {mean.start_icrs.dec_deg:+.4f} (ICRS). "
        f"Mean end: RA {mean.end_icrs.ra_deg:.4f}, "
        f"Dec {mean.end_icrs.dec_deg:+.4f} (ICRS). "
        f"Visible angular trail length: {mean.trail_length_deg:.4f} deg."
    )
    model_inputs = (
        f"Provisional radiant '{radiant['name']}' at RA {radiant['ra_deg']:.4f}, "
        f"Dec {radiant['dec_deg']:+.4f} ({radiant['frame']}). This is a declared "
        "model input, not a confirmed catalogue truth."
    )
    uncertainty = (
        "Selection-only Monte Carlo "
        f"(n={mc['n_samples_used']}/{mc['n_samples_requested']}, seed={seed}): "
        f"trail length median {mc['trail_length_deg_median']:.4f} deg "
        f"[{mc['trail_length_deg_p2_5']:.4f}, "
        f"{mc['trail_length_deg_p97_5']:.4f}] (95%); "
        f"cross-track median {mc['cross_track_deg_median']:.4f} deg "
        f"[{mc['cross_track_deg_p2_5']:.4f}, "
        f"{mc['cross_track_deg_p97_5']:.4f}] (95%); "
        f"alignment fractions {mc['alignment_fraction']}. This reflects "
        "repeated-selection variability only, not WCS residuals, radiant "
        "dispersion, frame systematics, or camera-specific "
        "computational-photography effects."
    )
    wcs_residuals = (
        "WCS internal correspondence residuals "
        f"(n={validation['residuals']['match_count']}): "
        f"median {validation['residuals']['median_arcsec']:.2f} arcsec, "
        f"p68 {validation['residuals']['p68_arcsec']:.2f} arcsec, "
        f"p95 {validation['residuals']['p95_arcsec']:.2f} arcsec, "
        f"max {validation['residuals']['max_arcsec']:.2f} arcsec. These are "
        "in-sample solution diagnostics, not an independent holdout "
        "calibration of external astrometric accuracy."
    )
    supported = (
        f"Alignment classification: {mean.alignment.value}. This describes "
        "geometric consistency between the observed trail's great circle "
        "and the provisional radiant, propagated through repeated-selection "
        "uncertainty only."
    )
    unsupported = (
        "This report does not establish confirmed shower membership, "
        "physical speed, altitude, brightness, colour, or fragmentation. "
        "WCS residuals here are internal consistency checks, not external "
        "calibration."
    )

    return {
        "Observations": observations,
        "Image-derived measurements": measurements,
        "Model inputs": model_inputs,
        "Selection-only uncertainty": uncertainty,
        "WCS internal residuals": wcs_residuals,
        "Supported conclusion": supported,
        "Unsupported interpretations": unsupported,
    }
