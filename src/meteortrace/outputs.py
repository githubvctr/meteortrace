"""Output generation for trail analysis: JSON, CSV, figures, report and provenance.

Matplotlib is used with the non-interactive ``Agg`` backend here, since
these are batch output writers; `meteortrace.interactive_selection` sets
an interactive backend for the live click-selection tool instead.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Ellipse  # noqa: E402
from PIL import Image  # noqa: E402

from meteortrace.contracts import ObservedTrail, ShowerRadiant  # noqa: E402
from meteortrace.geometry import (
    point_at_along_track_angle_deg,
    trail_angular_length_deg,
)  # noqa: E402
from meteortrace.selection import ManualSelectionRecord  # noqa: E402
from meteortrace.trajectory import MeanTrajectoryResult  # noqa: E402
from meteortrace.uncertainty import EndpointStatistics  # noqa: E402


def write_analysis_json(path: Path, analysis: dict) -> None:
    """Write the analysis result as deterministically formatted JSON."""
    path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n")


def write_provenance_json(path: Path, provenance: dict) -> None:
    """Write the run's provenance manifest as deterministically formatted JSON."""
    path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")


def write_trajectory_csv(path: Path, trail: ObservedTrail, n_points: int = 200) -> None:
    """Write an ordered, sampled great-circle path from `trail.start` to `trail.end`."""
    length_deg = trail_angular_length_deg(trail)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "along_track_deg", "ra_icrs_deg", "dec_icrs_deg"])
        for index, along_track_deg in enumerate(np.linspace(0.0, length_deg, n_points)):
            point = point_at_along_track_angle_deg(trail, float(along_track_deg))
            writer.writerow(
                [index, float(along_track_deg), point.ra_deg, point.dec_deg]
            )


def _covariance_ellipse(
    mean: tuple[float, float],
    covariance: tuple[tuple[float, float], tuple[float, float]],
    n_std: float,
    **kwargs,
) -> Ellipse | None:
    """A `n_std`-sigma covariance ellipse patch, or `None` if covariance is zero."""
    cov_array = np.array(covariance)
    if np.allclose(cov_array, 0.0):
        return None
    eigenvalues, eigenvectors = np.linalg.eigh(cov_array)
    order = eigenvalues.argsort()[::-1]
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    angle_deg = float(np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0])))
    width, height = 2 * n_std * np.sqrt(np.maximum(eigenvalues, 0.0))
    return Ellipse(xy=mean, width=width, height=height, angle=angle_deg, **kwargs)


def generate_image_overlay_png(
    path: Path,
    image_path: Path,
    selection: ManualSelectionRecord,
    start_stats: EndpointStatistics,
    end_stats: EndpointStatistics,
) -> None:
    """Render the solver image with clicks, mean endpoints and direction arrow."""
    image = Image.open(image_path)
    fig, ax = plt.subplots(figsize=(6, 8))
    ax.imshow(image)

    start_xy = [(c.x, c.y) for c in selection.start_clicks]
    end_xy = [(c.x, c.y) for c in selection.end_clicks]
    ax.scatter(
        *zip(*start_xy, strict=True),
        marker="x",
        color="deepskyblue",
        label="start clicks (repeated)",
    )
    ax.scatter(
        *zip(*end_xy, strict=True),
        marker="x",
        color="orange",
        label="end clicks (repeated)",
    )
    ax.scatter(
        [start_stats.mean_x],
        [start_stats.mean_y],
        color="blue",
        s=90,
        edgecolor="white",
        label="mean start",
    )
    ax.scatter(
        [end_stats.mean_x],
        [end_stats.mean_y],
        color="red",
        s=90,
        edgecolor="white",
        label="mean end",
    )
    ax.annotate(
        "",
        xy=(end_stats.mean_x, end_stats.mean_y),
        xytext=(start_stats.mean_x, start_stats.mean_y),
        arrowprops={"arrowstyle": "->", "color": "lime", "lw": 2},
    )

    for stats, color in ((start_stats, "blue"), (end_stats, "red")):
        ellipse = _covariance_ellipse(
            (stats.mean_x, stats.mean_y),
            stats.covariance,
            n_std=1.0,
            fill=False,
            edgecolor=color,
            linewidth=1.5,
            linestyle="--",
        )
        if ellipse is not None:
            ax.add_patch(ellipse)

    ax.set_title("Manual endpoint selection (human clicks, not automated detection)")
    ax.set_xlabel("x (pixel)")
    ax.set_ylabel("y (pixel)")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def generate_radiant_geometry_png(
    path: Path,
    trail: ObservedTrail,
    radiant: ShowerRadiant,
    mean_result: MeanTrajectoryResult,
) -> None:
    """Render the observed segment, backward extension, radiant and closest point."""
    length_deg = trail_angular_length_deg(trail)
    backward_extent_deg = max(length_deg, abs(mean_result.along_track_deg)) * 1.3 + 2.0

    segment = [
        point_at_along_track_angle_deg(trail, t)
        for t in np.linspace(0.0, length_deg, 50)
    ]
    backward = [
        point_at_along_track_angle_deg(trail, t)
        for t in np.linspace(0.0, -backward_extent_deg, 50)
    ]

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot(
        [p.ra_deg for p in segment],
        [p.dec_deg for p in segment],
        color="lime",
        lw=2,
        label="observed segment",
    )
    ax.plot(
        [p.ra_deg for p in backward],
        [p.dec_deg for p in backward],
        color="lime",
        lw=1.5,
        linestyle="--",
        label="backward extension",
    )
    ax.scatter(
        [radiant.coordinate.ra_deg],
        [radiant.coordinate.dec_deg],
        marker="*",
        s=200,
        color="gold",
        label=f"{radiant.name} (provisional)",
    )
    ax.scatter(
        [mean_result.closest_point_icrs.ra_deg],
        [mean_result.closest_point_icrs.dec_deg],
        marker="o",
        s=60,
        color="magenta",
        label="closest point on great circle",
    )
    ax.scatter(
        [trail.start.ra_deg],
        [trail.start.dec_deg],
        marker="^",
        color="blue",
        label="start (earlier)",
    )
    ax.scatter(
        [trail.end.ra_deg],
        [trail.end.dec_deg],
        marker="v",
        color="red",
        label="end (later)",
    )

    ax.set_xlabel("RA (deg, ICRS)")
    ax.set_ylabel("Dec (deg, ICRS)")
    ax.set_title("Geometric consistency check (not a confirmed radiant match)")
    ax.legend(loc="best", fontsize=8)
    ax.invert_xaxis()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_report_md(path: Path, report_sections: dict[str, str]) -> None:
    """Write `report.md` from an ordered mapping of section title -> markdown body."""
    lines = ["# MeteorTrace trail analysis report", ""]
    for title, body in report_sections.items():
        lines.append(f"## {title}")
        lines.append("")
        lines.append(body.strip())
        lines.append("")
    path.write_text("\n".join(lines) + "\n")
