"""Orchestration of provenance, image-metadata and WCS ingestion into one audit.

`run_audit` is the single entry point used by both the CLI and tests. It
performs no network access and never modifies its inputs.

Two scientific questions are kept strictly separate throughout (see
`docs/input_provenance_and_wcs.md`):

- **Reference-grid assessment**: does the WCS's solved pixel grid relate
  to the reference image's own pixel grid, and by what transform?
- **Target-transfer assessment**: can that WCS be used for a *different*
  image (the target), and under what evidence?

A dimension match is evidence about *what transform might apply*, never
proof of *which* transform (rotation direction, mirroring, cropping), and
never proof that two distinct files share a pixel grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import meteortrace
from meteortrace.astrometry import WcsSummary, load_wcs
from meteortrace.image import (
    HEIC_ORIENTATION_LIMITATION,
    ImageMetadata,
    capture_time_difference_seconds,
    read_image_metadata,
)
from meteortrace.provenance import FileRecord, build_file_record

AUDIT_SCHEMA_VERSION = "2.0"


class ReferenceGridStatus(Enum):
    """Whether the WCS's solved pixel grid relates to the reference image's own grid."""

    DIRECT_MATCH = "direct_match"
    TRANSFORM_REQUIRED = "transform_required"
    INCOMPATIBLE = "incompatible"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class TargetTransferStatus(Enum):
    """Whether a WCS solution may be used for a separately captured target image."""

    DIRECT_MATCH = "direct_match"
    REGISTRATION_REQUIRED = "registration_required"
    INCOMPATIBLE = "incompatible"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class ReferenceGridAssessment:
    """Conclusion about the WCS-to-reference-image pixel-grid relationship."""

    status: ReferenceGridStatus
    observations: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "observations": list(self.observations),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TargetTransferAssessment:
    """Conclusion about whether a WCS may be used for a separate target image."""

    status: TargetTransferStatus
    observations: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "observations": list(self.observations),
            "warnings": list(self.warnings),
        }


def assess_reference_grid(
    wcs_summary: WcsSummary,
    reference_metadata: ImageMetadata | None,
    derived_metadata: list[ImageMetadata],
) -> ReferenceGridAssessment:
    """Assess how the WCS's solved pixel grid relates to the reference image's own grid.

    A dimension match is evidence for a *candidate* transform, not proof
    of one: rotation direction, mirroring, cropping and resampling are
    not distinguishable from width/height alone, so any match that
    requires a swap (or that is only visible through a derived,
    third-party diagnostic image) is reported as `TRANSFORM_REQUIRED`,
    never `DIRECT_MATCH`.
    """
    observations: list[str] = []
    warnings: list[str] = []

    if reference_metadata is None:
        observations.append("Reference image metadata could not be read.")
        return ReferenceGridAssessment(
            ReferenceGridStatus.INSUFFICIENT_EVIDENCE,
            tuple(observations),
            tuple(warnings),
        )

    wcs_dims = (wcs_summary.width, wcs_summary.height)
    ref_encoded = (reference_metadata.encoded_width, reference_metadata.encoded_height)
    ref_display = (reference_metadata.display_width, reference_metadata.display_height)
    ref_transposed = (ref_encoded[1], ref_encoded[0])

    if wcs_dims == ref_encoded:
        observations.append(
            f"WCS pixel grid {wcs_dims} matches the reference image's encoded "
            "grid directly; no transform is required for the dimensions to align."
        )
        return ReferenceGridAssessment(
            ReferenceGridStatus.DIRECT_MATCH, tuple(observations), tuple(warnings)
        )

    if ref_display != ref_encoded and wcs_dims == ref_display:
        observations.append(
            f"WCS pixel grid {wcs_dims} matches the reference image's "
            "orientation-normalized display grid, using the file's own "
            f"established EXIF orientation ({reference_metadata.exif_orientation})."
        )
        return ReferenceGridAssessment(
            ReferenceGridStatus.DIRECT_MATCH, tuple(observations), tuple(warnings)
        )

    if wcs_dims == ref_transposed:
        observations.append(
            f"WCS pixel grid {wcs_dims} is transposed (width/height swapped) "
            f"relative to the reference image's encoded grid {ref_encoded}. "
            f"The reference image's own EXIF orientation "
            f"({reference_metadata.exif_orientation}) does not account for "
            "this swap."
        )
        warnings.append(
            "A width/height transpose is consistent with a candidate rotation "
            "(e.g. 90 degrees) or another derived representation, but this "
            "program has not derived or validated rotation direction, "
            "mirroring, cropping or resampling from image content. The "
            "explicit transform from the locally decoded reference grid to "
            "the WCS-solved grid remains unresolved."
        )
        return ReferenceGridAssessment(
            ReferenceGridStatus.TRANSFORM_REQUIRED, tuple(observations), tuple(warnings)
        )

    for meta in derived_metadata:
        derived_dims = (meta.encoded_width, meta.encoded_height)
        if derived_dims == wcs_dims:
            observations.append(
                f"WCS pixel grid {wcs_dims} matches derived image ({meta.role}) "
                f"dimensions, not the reference image's own encoded "
                f"{ref_encoded} or display {ref_display} grid."
            )
            warnings.append(
                "The match above is via a separate derived diagnostic file, "
                "known only by role and provenance, not by a validated pixel "
                "transform back to the reference image. Astrometry.net's "
                "upload/processing pipeline may have rotated, cropped or "
                "resampled the submitted image in ways this program does not "
                "verify."
            )
            return ReferenceGridAssessment(
                ReferenceGridStatus.TRANSFORM_REQUIRED,
                tuple(observations),
                tuple(warnings),
            )

    observations.append(
        f"WCS pixel grid {wcs_dims} matches none of: reference encoded "
        f"{ref_encoded}, reference display {ref_display}, its transpose "
        f"{ref_transposed}, or any supplied derived image dimensions."
    )
    return ReferenceGridAssessment(
        ReferenceGridStatus.INCOMPATIBLE, tuple(observations), tuple(warnings)
    )


def assess_target_transfer(
    reference_grid_status: ReferenceGridStatus,
    reference_metadata: ImageMetadata | None,
    target_metadata: ImageMetadata | None,
    reference_record: FileRecord | None,
    target_record: FileRecord | None,
) -> TargetTransferAssessment:
    """Assess whether a WCS solution may be used for a separately captured target.

    `DIRECT_MATCH` is reachable only when the reference and target are
    proven to be the same file by hash *and* their relevant pixel grids
    directly match — never from matching dimensions or metadata on two
    distinct files. There is no bare Boolean "trust me" escape hatch: a
    future structured registration-result contract (transformation model,
    residuals, matched points, inlier count, provenance) would be
    required to justify anything stronger for distinct files, and is not
    implemented here.
    """
    observations: list[str] = []
    warnings: list[str] = []

    if (
        reference_metadata is None
        or target_metadata is None
        or reference_record is None
        or target_record is None
    ):
        observations.append("Reference or target image metadata could not be read.")
        return TargetTransferAssessment(
            TargetTransferStatus.INSUFFICIENT_EVIDENCE,
            tuple(observations),
            tuple(warnings),
        )

    if reference_grid_status is ReferenceGridStatus.INSUFFICIENT_EVIDENCE:
        observations.append(
            "Reference-grid assessment was inconclusive; target transfer "
            "cannot be assessed from it."
        )
        return TargetTransferAssessment(
            TargetTransferStatus.INSUFFICIENT_EVIDENCE,
            tuple(observations),
            tuple(warnings),
        )

    if reference_grid_status is ReferenceGridStatus.INCOMPATIBLE:
        observations.append(
            "Reference-grid assessment is INCOMPATIBLE; a WCS that does not "
            "even relate to its own reference image cannot be transferred "
            "to a target."
        )
        return TargetTransferAssessment(
            TargetTransferStatus.INCOMPATIBLE, tuple(observations), tuple(warnings)
        )

    same_file = reference_record.sha256 == target_record.sha256
    ref_encoded = (reference_metadata.encoded_width, reference_metadata.encoded_height)
    target_encoded = (target_metadata.encoded_width, target_metadata.encoded_height)
    grid_matches = target_encoded == ref_encoded

    if same_file:
        observations.append("Reference and target are the same file by hash.")
    else:
        observations.append(
            "Reference and target are confirmed distinct files by hash."
        )

    if target_encoded == ref_encoded:
        observations.append(
            f"Target encoded dimensions {target_encoded} match reference."
        )
    else:
        observations.append(
            f"Target encoded dimensions {target_encoded} differ from "
            f"reference {ref_encoded}."
        )

    if target_metadata.exif_orientation == reference_metadata.exif_orientation:
        observations.append(
            f"Target EXIF orientation ({target_metadata.exif_orientation}) "
            "matches reference."
        )
    else:
        observations.append(
            f"Target EXIF orientation ({target_metadata.exif_orientation}) "
            f"differs from reference ({reference_metadata.exif_orientation})."
        )

    if (target_metadata.camera_make, target_metadata.camera_model) == (
        reference_metadata.camera_make,
        reference_metadata.camera_model,
    ):
        observations.append("Target camera make/model matches reference.")
    else:
        observations.append("Target camera make/model differs from reference.")

    if target_metadata.lens_model == reference_metadata.lens_model:
        observations.append("Target lens model matches reference.")
    else:
        observations.append("Target lens model differs from reference.")

    if target_metadata.focal_length_mm == reference_metadata.focal_length_mm:
        observations.append("Target focal length matches reference.")
    else:
        observations.append(
            f"Target focal length ({target_metadata.focal_length_mm} mm) differs from "
            f"reference ({reference_metadata.focal_length_mm} mm)."
        )

    time_diff = capture_time_difference_seconds(reference_metadata, target_metadata)
    if time_diff is not None:
        if time_diff > 0:
            ordering = "reference recorded before target"
        elif time_diff < 0:
            ordering = "target recorded before reference"
        else:
            ordering = "identical recorded timestamps"
        observations.append(
            f"Recorded capture timestamps are {abs(time_diff):.1f} s apart "
            f"({ordering}), derived from each file's DateTimeOriginal + "
            "OffsetTimeOriginal EXIF fields."
        )
    else:
        observations.append(
            "Capture-time difference not computed: DateTimeOriginal with an "
            "explicit OffsetTimeOriginal is not present for both images, and "
            "none was invented."
        )

    if same_file and grid_matches:
        observations.append(
            "Reference and target are proven identical by hash, with matching "
            "pixel grids: there is no actual transfer being performed."
        )
        return TargetTransferAssessment(
            TargetTransferStatus.DIRECT_MATCH, tuple(observations), tuple(warnings)
        )

    observations.append(
        "Matching dimensions, orientation and camera metadata alone do not "
        "constitute measured pixel registration between distinct files. No "
        "structured registration result (transformation model, residuals, "
        "matched points, inlier count) was supplied."
    )
    return TargetTransferAssessment(
        TargetTransferStatus.REGISTRATION_REQUIRED,
        tuple(observations),
        tuple(warnings),
    )


def run_audit(
    reference_image: Path,
    target_image: Path,
    wcs_path: Path,
    derived_images: list[Path] | None = None,
) -> dict:
    """Run the full input-provenance and WCS-ingestion audit.

    Performs no network access. All inputs are opened read-only.

    Raises
    ------
    FileNotFoundError
        If any input file does not exist.
    DimensionResolutionError
        If the WCS's pixel dimensions cannot be resolved unambiguously.
    """
    derived_images = derived_images or []
    warnings: list[str] = []

    reference_metadata = read_image_metadata(reference_image, role="reference")
    target_metadata = read_image_metadata(target_image, role="target")
    derived_metadata = [
        read_image_metadata(path, role=f"derived_diagnostic:{path.name}")
        for path in derived_images
    ]

    reference_record = build_file_record(
        reference_image,
        role="reference",
        detected_format=reference_metadata.file_format,
    )
    target_record = build_file_record(
        target_image, role="target", detected_format=target_metadata.file_format
    )
    wcs_record = build_file_record(wcs_path, role="wcs", detected_format="FITS")
    derived_records = [
        build_file_record(
            path,
            role=f"derived_diagnostic:{path.name}",
            detected_format=meta.file_format,
        )
        for path, meta in zip(derived_images, derived_metadata, strict=False)
    ]

    _, wcs_summary = load_wcs(wcs_path)

    reference_grid_assessment = assess_reference_grid(
        wcs_summary=wcs_summary,
        reference_metadata=reference_metadata,
        derived_metadata=derived_metadata,
    )
    target_transfer_assessment = assess_target_transfer(
        reference_grid_status=reference_grid_assessment.status,
        reference_metadata=reference_metadata,
        target_metadata=target_metadata,
        reference_record=reference_record,
        target_record=target_record,
    )

    if wcs_summary.header_radesys is None:
        warnings.append(
            "WCS header does not declare RADESYS explicitly; "
            f"Astropy's inferred frame ({wcs_summary.astropy_inferred_radesys}) "
            "is reported separately and is not asserted to be ICRS."
        )

    warnings.append(HEIC_ORIENTATION_LIMITATION)

    all_records = [reference_record, target_record, wcs_record, *derived_records]
    all_metadata = [reference_metadata, target_metadata, *derived_metadata]

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "package_version": meteortrace.__version__,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "files": [record.to_dict() for record in all_records],
        "images": [metadata.to_dict() for metadata in all_metadata],
        "wcs": wcs_summary.to_dict(),
        "reference_grid_assessment": reference_grid_assessment.to_dict(),
        "target_transfer_assessment": target_transfer_assessment.to_dict(),
        "warnings": warnings,
    }
