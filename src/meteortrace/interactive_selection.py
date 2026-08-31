"""Interactive Matplotlib-based repeated trail-endpoint click collection.

`collect_selection_via_matplotlib` is the single seam between the
`select-trail` CLI and an actual GUI: tests replace this function (it is
a plain, importable, monkeypatchable callable) rather than driving a real
window, since no real human clicks may be fabricated by this package.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from meteortrace.selection import PixelClick


class SelectionCancelledError(RuntimeError):
    """Raised when a user cancels a click-selection session before completion."""


class NonInteractiveBackendError(RuntimeError):
    """Raised when no interactive Matplotlib backend is available for clicking."""


# Backends that cannot display a window or receive click events; attempting
# `ginput` under one of these blocks forever waiting for events that can
# never arrive, so this is checked explicitly rather than left to hang.
_NON_INTERACTIVE_BACKENDS = {"agg", "pdf", "ps", "svg", "cairo", "template"}

# A finite upper bound on how long one click pair may take, so a
# misconfigured or headless environment fails loudly instead of hanging
# indefinitely even if the backend guard above is somehow bypassed.
_GINPUT_TIMEOUT_SECONDS = 3600


def collect_selection_via_matplotlib(
    image_path: Path, repeats: int
) -> tuple[tuple[PixelClick, ...], tuple[PixelClick, ...]]:
    """Collect `repeats` repeated (start, end) click pairs on `image_path`.

    Shows the image in its native, zero-based pixel orientation (no
    orientation transform is applied: this is only used for the direct
    solver PNG, which has no ambiguous EXIF orientation). Draws the
    selected line after every completed pair. Raises
    `SelectionCancelledError`, without returning a partial result, if the
    window is closed or a pair is not completed.

    Raises
    ------
    SelectionCancelledError
        If the user cancels before completing all `repeats` pairs.
    NonInteractiveBackendError
        If no interactive Matplotlib backend is available.
    """
    import matplotlib.pyplot as plt  # deferred: only needed for the real path

    backend = plt.get_backend().lower()
    if backend in _NON_INTERACTIVE_BACKENDS:
        raise NonInteractiveBackendError(
            f"Matplotlib backend {backend!r} cannot display a window or receive "
            "clicks. Set the MPLBACKEND environment variable to an interactive "
            "backend (e.g. 'MacOSX', 'TkAgg', 'QtAgg') and try again."
        )

    image = Image.open(image_path)
    fig, ax = plt.subplots()
    ax.imshow(image)
    ax.set_title(
        f"Click EARLIER endpoint, then LATER endpoint. Repetition 1/{repeats}.\n"
        "Zoom/pan first if needed; close the window to cancel."
    )
    ax.set_xlabel("x (pixel)")
    ax.set_ylabel("y (pixel)")
    fig.canvas.manager.set_window_title("MeteorTrace: select trail endpoints")

    start_clicks: list[PixelClick] = []
    end_clicks: list[PixelClick] = []

    print(
        "MeteorTrace manual trail selection: for each repetition, click the "
        "EARLIER (start) endpoint first, then the LATER (end) endpoint. "
        "You may zoom/pan the window before each click using the toolbar. "
        "Close the window at any time to cancel without saving."
    )

    for repetition in range(1, repeats + 1):
        ax.set_title(
            f"Repetition {repetition}/{repeats}: click EARLIER endpoint, "
            "then LATER endpoint."
        )
        fig.canvas.draw()
        points = fig.ginput(n=2, timeout=_GINPUT_TIMEOUT_SECONDS)
        if len(points) < 2:
            plt.close(fig)
            raise SelectionCancelledError(
                f"Selection cancelled during repetition {repetition}/{repeats}: "
                "fewer than 2 points were clicked."
            )
        start_x, start_y = points[0]
        end_x, end_y = points[1]
        start_clicks.append(PixelClick(x=start_x, y=start_y))
        end_clicks.append(PixelClick(x=end_x, y=end_y))
        ax.plot(
            [start_x, end_x], [start_y, end_y], color="lime", linewidth=1.5, marker="x"
        )
        fig.canvas.draw()

    plt.close(fig)
    return tuple(start_clicks), tuple(end_clicks)
