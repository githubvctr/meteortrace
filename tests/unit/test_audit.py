"""Unit tests for `meteortrace.audit` reference-grid and target-transfer assessments."""

from __future__ import annotations

from meteortrace.astrometry import WcsSummary
from meteortrace.audit import (
    ReferenceGridStatus,
    TargetTransferStatus,
    assess_reference_grid,
    assess_target_transfer,
)
from meteortrace.image import ImageMetadata
from meteortrace.provenance import FileRecord


def _wcs_summary(width: int, height: int) -> WcsSummary:
    return WcsSummary(
        width=width,
        height=height,
        dimension_sources={"IMAGEW_IMAGEH": (width, height)},
        naxis=2,
        ctype=("RA---TAN", "DEC--TAN"),
        crpix=(1.0, 1.0),
        crval=(10.0, 20.0),
        cd_matrix=((-0.001, 0.0), (0.0, 0.001)),
        header_radesys=None,
        astropy_inferred_radesys="FK5",
        equinox=2000.0,
        has_celestial=True,
        has_sip=False,
        sip_orders=None,
    )


def _image_metadata(
    role: str,
    encoded_width: int,
    encoded_height: int,
    exif_orientation: int = 1,
    display_width: int | None = None,
    display_height: int | None = None,
    camera_make: str | None = "Apple",
    camera_model: str | None = "iPhone",
    lens_model: str | None = "Lens",
    focal_length_mm: float | None = 6.0,
    capture_datetime_recorded: str | None = None,
    capture_utc_offset: str | None = None,
) -> ImageMetadata:
    return ImageMetadata(
        role=role,
        file_format="HEIF",
        color_mode="RGB",
        encoded_width=encoded_width,
        encoded_height=encoded_height,
        display_width=display_width if display_width is not None else encoded_width,
        display_height=(
            display_height if display_height is not None else encoded_height
        ),
        exif_orientation=exif_orientation,
        camera_make=camera_make,
        camera_model=camera_model,
        lens_model=lens_model,
        focal_length_mm=focal_length_mm,
        focal_length_35mm_equiv=24,
        capture_datetime_recorded=capture_datetime_recorded,
        capture_utc_offset=capture_utc_offset,
        has_gps=True,
    )


def _file_record(role: str, sha256: str) -> FileRecord:
    return FileRecord(role=role, name=f"{role}.heic", byte_size=1000, sha256=sha256)


# --- Reference-grid assessment ---------------------------------------------


def test_direct_encoded_dimension_match_is_reference_direct_match() -> None:
    wcs_summary = _wcs_summary(100, 60)
    reference = _image_metadata("reference", 100, 60)

    assessment = assess_reference_grid(wcs_summary, reference, [])

    assert assessment.status is ReferenceGridStatus.DIRECT_MATCH
    assert not assessment.warnings


def test_transposed_dimensions_yield_transform_required_not_direct_match() -> None:
    wcs_summary = _wcs_summary(4032, 3024)
    reference = _image_metadata("reference", 3024, 4032, exif_orientation=1)

    assessment = assess_reference_grid(wcs_summary, reference, [])

    assert assessment.status is ReferenceGridStatus.TRANSFORM_REQUIRED
    assert assessment.status is not ReferenceGridStatus.DIRECT_MATCH
    assert any("transpose" in warning.lower() for warning in assessment.warnings)
    assert any("not derived or validated" in warning for warning in assessment.warnings)


def test_dimension_mismatch_yields_incompatible() -> None:
    wcs_summary = _wcs_summary(4032, 3024)
    reference = _image_metadata("reference", 200, 100)

    assessment = assess_reference_grid(wcs_summary, reference, [])

    assert assessment.status is ReferenceGridStatus.INCOMPATIBLE


def test_missing_reference_metadata_is_insufficient_evidence() -> None:
    wcs_summary = _wcs_summary(100, 60)
    assessment = assess_reference_grid(wcs_summary, None, [])
    assert assessment.status is ReferenceGridStatus.INSUFFICIENT_EVIDENCE


def test_match_via_derived_image_is_transform_required_not_direct_match() -> None:
    wcs_summary = _wcs_summary(4032, 3024)
    # Reference dims unrelated (not equal, transposed, or display-normalized
    # relative to the WCS grid) so only the derived image can match.
    reference = _image_metadata("reference", 500, 500)
    derived = _image_metadata("derived_diagnostic:x.jpg", 4032, 3024)

    assessment = assess_reference_grid(wcs_summary, reference, [derived])

    assert assessment.status is ReferenceGridStatus.TRANSFORM_REQUIRED
    assert any("derived image" in obs for obs in assessment.observations)
    assert any("not verify" in warning for warning in assessment.warnings)


def test_display_normalized_match_is_direct_match_when_orientation_known() -> None:
    # A rotated encoded grid whose EXIF orientation transform is known and
    # already accounts for the swap is a DIRECT_MATCH, not a hypothesis.
    wcs_summary = _wcs_summary(4032, 3024)
    reference = _image_metadata(
        "reference",
        3024,
        4032,
        exif_orientation=6,
        display_width=4032,
        display_height=3024,
    )

    assessment = assess_reference_grid(wcs_summary, reference, [])

    assert assessment.status is ReferenceGridStatus.DIRECT_MATCH


# --- Target-transfer assessment ---------------------------------------------


def test_matching_dimensions_alone_never_yields_target_direct_match() -> None:
    reference = _image_metadata("reference", 100, 60)
    target = _image_metadata("target", 100, 60)
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH,
        reference,
        target,
        reference_record,
        target_record,
    )

    assert assessment.status is not TargetTransferStatus.DIRECT_MATCH
    assert assessment.status is TargetTransferStatus.REGISTRATION_REQUIRED


def test_identical_metadata_on_distinct_files_requires_registration() -> None:
    reference = _image_metadata(
        "reference",
        100,
        60,
        capture_datetime_recorded="2026-08-12T00:34:15",
        capture_utc_offset="+02:00",
    )
    target = _image_metadata(
        "target",
        100,
        60,
        capture_datetime_recorded="2026-08-12T00:34:49",
        capture_utc_offset="+02:00",
    )
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.TRANSFORM_REQUIRED,
        reference,
        target,
        reference_record,
        target_record,
    )

    assert assessment.status is TargetTransferStatus.REGISTRATION_REQUIRED
    assert any("34.0" in obs for obs in assessment.observations)
    assert any("distinct files by hash" in obs for obs in assessment.observations)


def test_same_file_hash_and_matching_grid_yields_target_direct_match() -> None:
    reference = _image_metadata("reference", 100, 60)
    target = _image_metadata("target", 100, 60)
    same_record_a = _file_record("reference", "c" * 64)
    same_record_b = _file_record("target", "c" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH,
        reference,
        target,
        same_record_a,
        same_record_b,
    )

    assert assessment.status is TargetTransferStatus.DIRECT_MATCH


def test_same_hash_but_different_grid_still_requires_registration() -> None:
    # Defensive case only: identical bytes cannot actually decode to
    # different dimensions, but the rule is checked explicitly regardless.
    reference = _image_metadata("reference", 100, 60)
    target = _image_metadata("target", 200, 120)
    same_record_a = _file_record("reference", "c" * 64)
    same_record_b = _file_record("target", "c" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH,
        reference,
        target,
        same_record_a,
        same_record_b,
    )

    assert assessment.status is TargetTransferStatus.REGISTRATION_REQUIRED


def test_reference_incompatible_propagates_to_target_incompatible() -> None:
    reference = _image_metadata("reference", 100, 60)
    target = _image_metadata("target", 100, 60)
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.INCOMPATIBLE,
        reference,
        target,
        reference_record,
        target_record,
    )

    assert assessment.status is TargetTransferStatus.INCOMPATIBLE


def test_reference_insufficient_propagates_to_target_insufficient() -> None:
    reference = _image_metadata("reference", 100, 60)
    target = _image_metadata("target", 100, 60)
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.INSUFFICIENT_EVIDENCE,
        reference,
        target,
        reference_record,
        target_record,
    )

    assert assessment.status is TargetTransferStatus.INSUFFICIENT_EVIDENCE


def test_missing_target_metadata_is_insufficient_evidence() -> None:
    reference = _image_metadata("reference", 100, 60)
    reference_record = _file_record("reference", "a" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH, reference, None, reference_record, None
    )

    assert assessment.status is TargetTransferStatus.INSUFFICIENT_EVIDENCE


def test_all_target_metadata_differences_are_observed() -> None:
    reference = _image_metadata(
        "reference",
        100,
        60,
        exif_orientation=1,
        camera_make="Apple",
        camera_model="iPhone",
        lens_model="Lens A",
        focal_length_mm=6.0,
    )
    target = _image_metadata(
        "target",
        200,
        120,
        exif_orientation=6,
        camera_make="Samsung",
        camera_model="Galaxy",
        lens_model="Lens B",
        focal_length_mm=4.0,
    )
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH,
        reference,
        target,
        reference_record,
        target_record,
    )

    joined = " ".join(assessment.observations)
    assert "differ from reference" in joined
    assert "differs from reference" in joined
    assert "camera make/model differs" in joined
    assert "lens model differs" in joined


def test_timestamp_ordering_is_stated_explicitly() -> None:
    reference = _image_metadata(
        "reference",
        100,
        60,
        capture_datetime_recorded="2026-08-12T00:34:15",
        capture_utc_offset="+02:00",
    )
    target = _image_metadata(
        "target",
        100,
        60,
        capture_datetime_recorded="2026-08-12T00:34:49",
        capture_utc_offset="+02:00",
    )
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH,
        reference,
        target,
        reference_record,
        target_record,
    )

    joined = " ".join(assessment.observations)
    assert "34.0 s apart" in joined
    assert "reference recorded before target" in joined


def test_negative_timestamp_difference_states_target_recorded_first() -> None:
    reference = _image_metadata(
        "reference",
        100,
        60,
        capture_datetime_recorded="2026-08-12T00:35:00",
        capture_utc_offset="+02:00",
    )
    target = _image_metadata(
        "target",
        100,
        60,
        capture_datetime_recorded="2026-08-12T00:34:00",
        capture_utc_offset="+02:00",
    )
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    assessment = assess_target_transfer(
        ReferenceGridStatus.DIRECT_MATCH,
        reference,
        target,
        reference_record,
        target_record,
    )

    joined = " ".join(assessment.observations)
    assert "60.0 s apart" in joined
    assert "target recorded before reference" in joined


# --- Serialization -----------------------------------------------------------


def test_reference_and_target_assessment_serialization_is_deterministic() -> None:
    wcs_summary = _wcs_summary(100, 60)
    reference = _image_metadata("reference", 100, 60)
    target = _image_metadata("target", 100, 60)
    reference_record = _file_record("reference", "a" * 64)
    target_record = _file_record("target", "b" * 64)

    ref_a = assess_reference_grid(wcs_summary, reference, [])
    ref_b = assess_reference_grid(wcs_summary, reference, [])
    assert ref_a.to_dict() == ref_b.to_dict()

    target_a = assess_target_transfer(
        ref_a.status, reference, target, reference_record, target_record
    )
    target_b = assess_target_transfer(
        ref_b.status, reference, target, reference_record, target_record
    )
    assert target_a.to_dict() == target_b.to_dict()
