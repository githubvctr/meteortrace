"""Unit tests for `meteortrace.uncertainty`."""

from __future__ import annotations

import numpy as np
import pytest

from meteortrace.selection import PixelClick
from meteortrace.uncertainty import (
    compute_endpoint_statistics,
    sample_endpoints_monte_carlo,
)


def test_covariance_captures_correlated_x_y() -> None:
    # Clicks along a diagonal line: x and y should be strongly correlated.
    clicks = tuple(PixelClick(x=100.0 + i, y=200.0 + i) for i in range(6))
    stats = compute_endpoint_statistics(clicks)
    assert stats.covariance[0][1] == pytest.approx(stats.covariance[0][0], rel=1e-6)
    assert stats.covariance[0][1] > 0


def test_zero_covariance_for_identical_clicks() -> None:
    clicks = tuple(PixelClick(x=50.0, y=60.0) for _ in range(4))
    stats = compute_endpoint_statistics(clicks)
    assert stats.covariance == ((0.0, 0.0), (0.0, 0.0))
    assert stats.std_x == 0.0
    assert stats.std_y == 0.0
    assert stats.radial_rms == 0.0


def test_mean_and_n_repeats_are_correct() -> None:
    clicks = tuple(PixelClick(x=float(i), y=float(2 * i)) for i in range(1, 6))
    stats = compute_endpoint_statistics(clicks)
    assert stats.mean_x == pytest.approx(3.0)
    assert stats.mean_y == pytest.approx(6.0)
    assert stats.n_repeats == 5


def test_monte_carlo_is_deterministic_given_seed() -> None:
    start_clicks = tuple(PixelClick(x=100 + i * 0.3, y=200 - i * 0.2) for i in range(5))
    end_clicks = tuple(PixelClick(x=300 + i * 0.1, y=400 + i * 0.4) for i in range(5))
    start_stats = compute_endpoint_statistics(start_clicks)
    end_stats = compute_endpoint_statistics(end_clicks)

    mc_a = sample_endpoints_monte_carlo(
        start_stats, end_stats, n_samples=500, seed=42, width=1000, height=1000
    )
    mc_b = sample_endpoints_monte_carlo(
        start_stats, end_stats, n_samples=500, seed=42, width=1000, height=1000
    )

    assert np.array_equal(mc_a.start_xy, mc_b.start_xy)
    assert np.array_equal(mc_a.end_xy, mc_b.end_xy)


def test_monte_carlo_different_seed_differs() -> None:
    clicks = tuple(PixelClick(x=100 + i * 0.5, y=200 - i * 0.3) for i in range(5))
    stats = compute_endpoint_statistics(clicks)

    mc_a = sample_endpoints_monte_carlo(
        stats, stats, n_samples=200, seed=1, width=1000, height=1000
    )
    mc_b = sample_endpoints_monte_carlo(
        stats, stats, n_samples=200, seed=2, width=1000, height=1000
    )

    assert not np.array_equal(mc_a.start_xy, mc_b.start_xy)


def test_zero_covariance_monte_carlo_collapses_to_mean() -> None:
    clicks = tuple(PixelClick(x=50.0, y=60.0) for _ in range(4))
    stats = compute_endpoint_statistics(clicks)

    mc = sample_endpoints_monte_carlo(
        stats, stats, n_samples=100, seed=7, width=1000, height=1000
    )

    assert np.all(mc.start_xy == 50.0) is False or np.allclose(mc.start_xy[:, 0], 50.0)
    assert np.allclose(mc.start_xy, [50.0, 60.0])
    assert mc.n_rejected_start == 0


def test_monte_carlo_shapes_and_bounds() -> None:
    clicks = tuple(PixelClick(x=100 + i, y=100 + i) for i in range(5))
    stats = compute_endpoint_statistics(clicks)

    mc = sample_endpoints_monte_carlo(
        stats, stats, n_samples=1000, seed=5, width=1000, height=1000
    )
    assert mc.start_xy.shape == (1000, 2)
    assert mc.end_xy.shape == (1000, 2)
    assert np.all(mc.start_xy[:, 0] >= -0.5)
    assert np.all(mc.start_xy[:, 0] <= 999.5)


def test_out_of_bounds_samples_are_rejected_and_counted() -> None:
    # Large covariance relative to a tiny frame near the edge forces
    # rejections to occur and be counted explicitly.
    clicks = tuple(PixelClick(x=0.0 + i * 5.0, y=0.0 + i * 5.0) for i in range(5))
    stats = compute_endpoint_statistics(clicks)

    mc = sample_endpoints_monte_carlo(
        stats, stats, n_samples=200, seed=9, width=10, height=10
    )
    assert mc.start_xy.shape == (200, 2)
    assert np.all(mc.start_xy[:, 0] >= -0.5)
    assert np.all(mc.start_xy[:, 0] <= 9.5)
    assert mc.n_rejected_start > 0
