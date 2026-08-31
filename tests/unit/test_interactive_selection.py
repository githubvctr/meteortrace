"""Unit tests for `meteortrace.interactive_selection`, using a mocked Matplotlib figure.

No real GUI is driven: `collect_selection_via_matplotlib`'s internal
Matplotlib calls are mocked to simulate click sequences, since real human
clicks may never be fabricated by this package.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from meteortrace.interactive_selection import (
    NonInteractiveBackendError,
    SelectionCancelledError,
    collect_selection_via_matplotlib,
)


def _fake_pyplot(ginput_return_values: list[list[tuple[float, float]]]) -> MagicMock:
    fake_ax = MagicMock()
    fake_fig = MagicMock()
    fake_fig.canvas.manager.set_window_title = MagicMock()
    fake_fig.ginput.side_effect = ginput_return_values
    fake_plt = MagicMock()
    fake_plt.get_backend.return_value = "MacOSX"
    fake_plt.subplots.return_value = (fake_fig, fake_ax)
    return fake_plt


def _patch_pyplot(fake_plt: MagicMock):
    """Patch both `sys.modules` and the `matplotlib.pyplot` attribute.

    A plain `import matplotlib.pyplot as plt` resolves via whichever of
    these was already populated by an earlier real import elsewhere in
    the test session (order-dependent), so both must be patched together
    to reliably intercept it regardless of import order.
    """
    return (
        patch.dict("sys.modules", {"matplotlib.pyplot": fake_plt}),
        patch("matplotlib.pyplot", fake_plt, create=True),
    )


def test_collect_selection_returns_ordered_clicks(tmp_path: Path) -> None:
    image_path = tmp_path / "solver.png"
    Image.new("RGB", (50, 40), color=(1, 2, 3)).save(image_path)

    fake_plt = _fake_pyplot(
        [
            [(10.0, 20.0), (30.0, 25.0)],
            [(11.0, 21.0), (31.0, 26.0)],
            [(12.0, 22.0), (32.0, 27.0)],
        ]
    )
    patch_modules, patch_attr = _patch_pyplot(fake_plt)
    with patch_modules, patch_attr:
        start_clicks, end_clicks = collect_selection_via_matplotlib(
            image_path, repeats=3
        )

    assert len(start_clicks) == 3
    assert len(end_clicks) == 3
    assert (start_clicks[0].x, start_clicks[0].y) == (10.0, 20.0)
    assert (end_clicks[0].x, end_clicks[0].y) == (30.0, 25.0)
    assert (start_clicks[2].x, start_clicks[2].y) == (12.0, 22.0)


def test_collect_selection_cancelled_raises_without_partial_result(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "solver.png"
    Image.new("RGB", (50, 40), color=(1, 2, 3)).save(image_path)

    fake_plt = _fake_pyplot(
        [
            [(10.0, 20.0), (30.0, 25.0)],
            [(11.0, 21.0)],  # cancelled: only one point clicked
        ]
    )
    patch_modules, patch_attr = _patch_pyplot(fake_plt)
    with patch_modules, patch_attr:
        with pytest.raises(SelectionCancelledError):
            collect_selection_via_matplotlib(image_path, repeats=3)


def test_non_interactive_backend_raises_immediately_without_blocking(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "solver.png"
    Image.new("RGB", (50, 40), color=(1, 2, 3)).save(image_path)

    fake_plt = _fake_pyplot([[(10.0, 20.0), (30.0, 25.0)]])
    fake_plt.get_backend.return_value = "agg"
    patch_modules, patch_attr = _patch_pyplot(fake_plt)
    with patch_modules, patch_attr:
        with pytest.raises(NonInteractiveBackendError):
            collect_selection_via_matplotlib(image_path, repeats=1)
    fake_plt.subplots.assert_not_called()
