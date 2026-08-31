"""Immutable, validated contract for a repeated manual trail-endpoint selection.

A selection records a human's repeated clicks on a trail's visually
earlier ("start") and later ("end") endpoints, in a specific image's
`WCS_SOLVED` pixel space, together with enough provenance (file hashes,
dimensions) to detect later use against the wrong image or WCS. This
package never infers temporal direction from coordinate values: the
observed start->end order is a human judgement recorded at click time.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from meteortrace.pixels import PixelCoordinate, PixelSpace

SELECTION_SCHEMA_VERSION = "1.0"

_MIN_REPEATS = 3


@dataclass(frozen=True)
class PixelClick:
    """One raw click, in image pixel coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise ValueError(
                f"Click coordinates must be finite, got ({self.x}, {self.y})."
            )

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict) -> PixelClick:
        return cls(x=float(data["x"]), y=float(data["y"]))


@dataclass(frozen=True)
class ManualSelectionRecord:
    """A validated, repeated manual endpoint selection for one image/WCS pair.

    Parameters
    ----------
    schema_version : str
        Selection schema version.
    source_image_name : str
        Basename of the solver image the clicks were made on.
    source_image_role : str
        Logical role (e.g. ``"direct_solver_image"``).
    source_image_sha256 : str
        SHA-256 of the source image at selection time.
    wcs_sha256 : str
        SHA-256 of the WCS FITS file the image was solved against.
    image_width, image_height : int
        Pixel dimensions of the source image.
    pixel_space : str
        Must be ``"wcs_solved"``: only the direct PNG/WCS pair, where the
        image *is* the WCS-solved pixel grid, is supported.
    observed_direction : str
        Fixed descriptive label of the click-order convention used.
    start_clicks, end_clicks : tuple[PixelClick, ...]
        Repeated clicks for the earlier and later endpoint, respectively,
        in matching repetition order.
    selection_method : str
        e.g. ``"matplotlib_interactive"`` or a non-interactive test seam name.
    software_version : str
        MeteorTrace version that produced the selection.
    warnings : tuple[str, ...]
        Free-text notes; must not contain absolute paths.

    Raises
    ------
    ValueError
        If fewer than 3 repetitions are supplied, coordinates are
        out-of-bounds, start and end repetition counts differ, the pixel
        space is not ``"wcs_solved"``, or the mean start and end points
        are coincident.
    """

    schema_version: str
    source_image_name: str
    source_image_role: str
    source_image_sha256: str
    wcs_sha256: str
    image_width: int
    image_height: int
    pixel_space: str
    observed_direction: str
    start_clicks: tuple[PixelClick, ...]
    end_clicks: tuple[PixelClick, ...]
    selection_method: str
    software_version: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.pixel_space != PixelSpace.WCS_SOLVED.value:
            raise ValueError(
                "Only the WCS-solved pixel space is supported for manual "
                f"selection, got {self.pixel_space!r}."
            )
        if len(self.start_clicks) != len(self.end_clicks):
            raise ValueError(
                f"start_clicks ({len(self.start_clicks)}) and end_clicks "
                f"({len(self.end_clicks)}) must have equal repetition counts."
            )
        if len(self.start_clicks) < _MIN_REPEATS:
            raise ValueError(
                f"At least {_MIN_REPEATS} repeated endpoint pairs are required, "
                f"got {len(self.start_clicks)}."
            )
        for click in (*self.start_clicks, *self.end_clicks):
            if not (-0.5 <= click.x <= self.image_width - 0.5):
                raise ValueError(
                    f"Click x={click.x} is out of bounds for image width "
                    f"{self.image_width}."
                )
            if not (-0.5 <= click.y <= self.image_height - 0.5):
                raise ValueError(
                    f"Click y={click.y} is out of bounds for image height "
                    f"{self.image_height}."
                )
        for warning in self.warnings:
            if "/" in warning or "\\" in warning:
                raise ValueError(
                    "Selection warnings must not contain path separators "
                    f"(possible absolute path leak): {warning!r}."
                )
        start_mean_x = sum(c.x for c in self.start_clicks) / len(self.start_clicks)
        start_mean_y = sum(c.y for c in self.start_clicks) / len(self.start_clicks)
        end_mean_x = sum(c.x for c in self.end_clicks) / len(self.end_clicks)
        end_mean_y = sum(c.y for c in self.end_clicks) / len(self.end_clicks)
        if math.hypot(end_mean_x - start_mean_x, end_mean_y - start_mean_y) < 1e-9:
            raise ValueError(
                "Mean start and end endpoints are coincident; a degenerate "
                "trail cannot be analysed."
            )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_image_name": self.source_image_name,
            "source_image_role": self.source_image_role,
            "source_image_sha256": self.source_image_sha256,
            "wcs_sha256": self.wcs_sha256,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "pixel_space": self.pixel_space,
            "observed_direction": self.observed_direction,
            "start_clicks": [c.to_dict() for c in self.start_clicks],
            "end_clicks": [c.to_dict() for c in self.end_clicks],
            "selection_method": self.selection_method,
            "software_version": self.software_version,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ManualSelectionRecord:
        return cls(
            schema_version=data["schema_version"],
            source_image_name=data["source_image_name"],
            source_image_role=data["source_image_role"],
            source_image_sha256=data["source_image_sha256"],
            wcs_sha256=data["wcs_sha256"],
            image_width=int(data["image_width"]),
            image_height=int(data["image_height"]),
            pixel_space=data["pixel_space"],
            observed_direction=data["observed_direction"],
            start_clicks=tuple(PixelClick.from_dict(c) for c in data["start_clicks"]),
            end_clicks=tuple(PixelClick.from_dict(c) for c in data["end_clicks"]),
            selection_method=data["selection_method"],
            software_version=data["software_version"],
            warnings=tuple(data.get("warnings", ())),
        )


def save_selection(record: ManualSelectionRecord, path: Path) -> None:
    """Serialize `record` to `path` as deterministically formatted JSON."""
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n")


def load_selection(path: Path) -> ManualSelectionRecord:
    """Load and re-validate a `ManualSelectionRecord` from `path`.

    Raises
    ------
    FileNotFoundError
        If `path` does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path.name!r}")
    return ManualSelectionRecord.from_dict(json.loads(path.read_text()))


def verify_selection_against_inputs(
    record: ManualSelectionRecord,
    image_sha256: str,
    wcs_sha256: str,
    image_width: int,
    image_height: int,
) -> None:
    """Verify a selection was made against the exact image/WCS now being analysed.

    Raises
    ------
    ValueError
        If any hash or dimension does not match.
    """
    if record.source_image_sha256 != image_sha256:
        raise ValueError(
            "Selection's source image SHA-256 does not match the image "
            "supplied for analysis; the selection was made on a different file."
        )
    if record.wcs_sha256 != wcs_sha256:
        raise ValueError(
            "Selection's WCS SHA-256 does not match the WCS supplied for "
            "analysis; the selection was made against a different WCS."
        )
    if (record.image_width, record.image_height) != (image_width, image_height):
        raise ValueError(
            f"Selection's recorded dimensions ({record.image_width}x"
            f"{record.image_height}) do not match the analysed image "
            f"({image_width}x{image_height})."
        )


def click_to_pixel_coordinate(click: PixelClick) -> PixelCoordinate:
    """Convert a raw click to a `WCS_SOLVED` `PixelCoordinate`."""
    return PixelCoordinate(x=click.x, y=click.y, space=PixelSpace.WCS_SOLVED)
