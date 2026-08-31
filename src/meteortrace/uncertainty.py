"""Repeated-selection uncertainty: empirical covariance and deterministic Monte Carlo.

This module quantifies only the variability of a human repeatedly
clicking the same visual endpoint. It does not model, and must not be
combined numerically with, WCS residuals, radiant dispersion, frame
systematics, or camera-specific computational-photography effects: those
are separate uncertainty sources reported independently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from meteortrace.selection import PixelClick

# Documented default seed for reproducible Monte Carlo sampling.
DEFAULT_MONTE_CARLO_SEED = 20260812

# Safety cap on resampling attempts when rejecting out-of-bounds draws,
# expressed as a multiple of the requested sample count.
_MAX_RESAMPLE_MULTIPLIER = 50


@dataclass(frozen=True)
class EndpointStatistics:
    """Sample statistics of repeated clicks on one endpoint.

    `covariance` is the full 2x2 sample covariance matrix (``ddof=1``):
    x/y errors are never assumed independent.
    """

    mean_x: float
    mean_y: float
    covariance: tuple[tuple[float, float], tuple[float, float]]
    std_x: float
    std_y: float
    radial_rms: float
    n_repeats: int

    def to_dict(self) -> dict:
        return {
            "mean_x": self.mean_x,
            "mean_y": self.mean_y,
            "covariance": [list(row) for row in self.covariance],
            "std_x": self.std_x,
            "std_y": self.std_y,
            "radial_rms": self.radial_rms,
            "n_repeats": self.n_repeats,
        }


def compute_endpoint_statistics(clicks: tuple[PixelClick, ...]) -> EndpointStatistics:
    """Compute mean, covariance and radial spread for one endpoint's repeated clicks."""
    xs = np.array([c.x for c in clicks], dtype=np.float64)
    ys = np.array([c.y for c in clicks], dtype=np.float64)
    mean_x, mean_y = float(xs.mean()), float(ys.mean())

    if len(clicks) < 2:
        covariance = ((0.0, 0.0), (0.0, 0.0))
    else:
        cov = np.cov(np.vstack([xs, ys]), ddof=1)
        covariance = (
            (float(cov[0, 0]), float(cov[0, 1])),
            (float(cov[1, 0]), float(cov[1, 1])),
        )

    radial_rms = float(np.sqrt(np.mean((xs - mean_x) ** 2 + (ys - mean_y) ** 2)))
    return EndpointStatistics(
        mean_x=mean_x,
        mean_y=mean_y,
        covariance=covariance,
        std_x=math.sqrt(max(0.0, covariance[0][0])),
        std_y=math.sqrt(max(0.0, covariance[1][1])),
        radial_rms=radial_rms,
        n_repeats=len(clicks),
    )


@dataclass(frozen=True)
class MonteCarloSamples:
    """Deterministic Monte Carlo draws for both endpoints."""

    start_xy: np.ndarray
    end_xy: np.ndarray
    n_rejected_start: int
    n_rejected_end: int
    seed: int
    n_samples: int


def _sample_in_bounds(
    mean: tuple[float, float],
    covariance: tuple[tuple[float, float], tuple[float, float]],
    n_samples: int,
    rng: np.random.Generator,
    width: int,
    height: int,
) -> tuple[np.ndarray, int]:
    """Draw `n_samples` in-bounds points from a bivariate normal, rejecting the rest.

    Zero covariance is handled explicitly by returning the mean
    deterministically, without adding arbitrary undocumented noise.
    """
    cov_array = np.array(covariance)
    if np.allclose(cov_array, 0.0):
        return np.tile(np.array(mean), (n_samples, 1)), 0

    accepted: list[np.ndarray] = []
    n_rejected = 0
    max_draws = n_samples * _MAX_RESAMPLE_MULTIPLIER
    drawn = 0
    batch_size = max(n_samples, 256)
    while len(accepted) < n_samples and drawn < max_draws:
        batch = rng.multivariate_normal(mean, cov_array, size=batch_size, method="svd")
        drawn += batch_size
        in_bounds = (
            (batch[:, 0] >= -0.5)
            & (batch[:, 0] <= width - 0.5)
            & (batch[:, 1] >= -0.5)
            & (batch[:, 1] <= height - 0.5)
        )
        n_rejected += int((~in_bounds).sum())
        accepted.extend(batch[in_bounds])

    if len(accepted) < n_samples:
        raise ValueError(
            f"Could not draw {n_samples} in-bounds Monte Carlo samples after "
            f"{max_draws} attempts; the empirical covariance may be too large "
            "relative to the image frame."
        )
    return np.array(accepted[:n_samples]), n_rejected


def sample_endpoints_monte_carlo(
    start_stats: EndpointStatistics,
    end_stats: EndpointStatistics,
    n_samples: int,
    seed: int,
    width: int,
    height: int,
) -> MonteCarloSamples:
    """Draw deterministic, seeded Monte Carlo samples for both endpoints.

    Sampling is parametric: each endpoint's empirical bivariate covariance
    is treated as the (Gaussian) selection-uncertainty model. The same
    `seed` always reproduces the same samples.
    """
    rng = np.random.default_rng(seed)
    start_xy, n_rejected_start = _sample_in_bounds(
        (start_stats.mean_x, start_stats.mean_y),
        start_stats.covariance,
        n_samples,
        rng,
        width,
        height,
    )
    end_xy, n_rejected_end = _sample_in_bounds(
        (end_stats.mean_x, end_stats.mean_y),
        end_stats.covariance,
        n_samples,
        rng,
        width,
        height,
    )
    return MonteCarloSamples(
        start_xy=start_xy,
        end_xy=end_xy,
        n_rejected_start=n_rejected_start,
        n_rejected_end=n_rejected_end,
        seed=seed,
        n_samples=n_samples,
    )
