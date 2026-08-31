"""Unit tests for `meteortrace.selection`."""

from __future__ import annotations

from pathlib import Path

import pytest

from meteortrace.pixels import PixelSpace
from meteortrace.selection import (
    ManualSelectionRecord,
    PixelClick,
    load_selection,
    save_selection,
    verify_selection_against_inputs,
)

_COMMON = {
    "schema_version": "1.0",
    "source_image_name": "solver.png",
    "source_image_role": "direct_solver_image",
    "source_image_sha256": "a" * 64,
    "wcs_sha256": "b" * 64,
    "image_width": 200,
    "image_height": 300,
    "pixel_space": PixelSpace.WCS_SOLVED.value,
    "observed_direction": "start_to_end",
    "selection_method": "test_seam",
    "software_version": "0.3.0",
}


def _clicks(coords: list[tuple[float, float]]) -> tuple[PixelClick, ...]:
    return tuple(PixelClick(x=x, y=y) for x, y in coords)


def _valid_record(**overrides) -> ManualSelectionRecord:
    kwargs = dict(_COMMON)
    kwargs["start_clicks"] = _clicks([(50.0, 60.0), (50.5, 60.2), (49.8, 59.9)])
    kwargs["end_clicks"] = _clicks([(150.0, 250.0), (150.3, 250.1), (149.9, 249.8)])
    kwargs.update(overrides)
    return ManualSelectionRecord(**kwargs)


def test_valid_selection_round_trips_through_dict() -> None:
    record = _valid_record()
    restored = ManualSelectionRecord.from_dict(record.to_dict())
    assert restored == record


def test_click_order_is_preserved() -> None:
    starts = [(10.0, 20.0), (11.0, 21.0), (12.0, 22.0)]
    ends = [(90.0, 95.0), (91.0, 96.0), (92.0, 97.0)]
    record = _valid_record(start_clicks=_clicks(starts), end_clicks=_clicks(ends))
    assert [(c.x, c.y) for c in record.start_clicks] == starts
    assert [(c.x, c.y) for c in record.end_clicks] == ends


def test_fewer_than_three_repeats_raises() -> None:
    with pytest.raises(ValueError):
        _valid_record(
            start_clicks=_clicks([(50.0, 60.0), (51.0, 61.0)]),
            end_clicks=_clicks([(150.0, 250.0), (151.0, 251.0)]),
        )


def test_mismatched_repeat_counts_raise() -> None:
    with pytest.raises(ValueError):
        _valid_record(
            start_clicks=_clicks([(50.0, 60.0), (51.0, 61.0), (52.0, 62.0)]),
            end_clicks=_clicks([(150.0, 250.0), (151.0, 251.0)]),
        )


def test_out_of_bounds_click_raises() -> None:
    with pytest.raises(ValueError):
        _valid_record(
            start_clicks=_clicks([(-10.0, 60.0), (50.0, 60.0), (50.0, 60.0)]),
        )


def test_wrong_pixel_space_raises() -> None:
    with pytest.raises(ValueError):
        _valid_record(pixel_space="encoded")


def test_coincident_mean_endpoints_raise() -> None:
    same = [(50.0, 60.0), (50.0, 60.0), (50.0, 60.0)]
    with pytest.raises(ValueError):
        _valid_record(start_clicks=_clicks(same), end_clicks=_clicks(same))


def test_warning_with_path_separator_raises() -> None:
    with pytest.raises(ValueError):
        _valid_record(warnings=("see /Users/example/file.png",))


def test_save_and_load_selection_round_trip(tmp_path: Path) -> None:
    record = _valid_record()
    path = tmp_path / "selection.json"
    save_selection(record, path)
    loaded = load_selection(path)
    assert loaded == record


def test_load_missing_selection_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_selection(tmp_path / "does_not_exist.json")


def test_verify_selection_against_inputs_detects_hash_mismatch() -> None:
    record = _valid_record()
    with pytest.raises(ValueError):
        verify_selection_against_inputs(
            record,
            image_sha256="c" * 64,
            wcs_sha256=record.wcs_sha256,
            image_width=record.image_width,
            image_height=record.image_height,
        )


def test_verify_selection_against_inputs_detects_dimension_mismatch() -> None:
    record = _valid_record()
    with pytest.raises(ValueError):
        verify_selection_against_inputs(
            record,
            image_sha256=record.source_image_sha256,
            wcs_sha256=record.wcs_sha256,
            image_width=999,
            image_height=999,
        )


def test_verify_selection_against_inputs_passes_for_matching_inputs() -> None:
    record = _valid_record()
    verify_selection_against_inputs(
        record,
        image_sha256=record.source_image_sha256,
        wcs_sha256=record.wcs_sha256,
        image_width=record.image_width,
        image_height=record.image_height,
    )
