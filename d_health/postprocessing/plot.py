from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

logger = logging.getLogger(__name__)

# Per-group colourmaps (Greens=adults, Oranges=children).
# For arbitrary groups we cycle through a small palette.
_DEFAULT_CMAPS = ("Greens", "Oranges", "Purples", "Blues", "Reds")


def plot_raster(
    data: np.ndarray,
    *,
    cmap: str,
    title: str,
    save_path: Path | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    show: bool = False,
) -> Path | None:
    """Plot a 2-D raster with a colour bar; optionally save to ``save_path``.

    NaN-safe: vmin / vmax default to ``np.nanmin`` / ``np.nanmax``.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    if vmin is None:
        vmin = float(np.nanmin(data)) if np.isfinite(np.nanmin(data)) else 0.0
    if vmax is None:
        vmax = float(np.nanmax(data)) if np.isfinite(np.nanmax(data)) else 1.0
    norm = Normalize(vmin=vmin, vmax=vmax)
    im = ax.imshow(data, cmap=cmap, norm=norm)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label(title)
    ax.set_title(title)

    saved: Path | None = None
    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        saved = save_path
        logger.info("Wrote plot %s", save_path)

    if show:
        plt.show()
    plt.close(fig)
    return saved


def plot_per_group(
    arrays: dict[str, np.ndarray],
    *,
    label: str,
    out_dir: Path,
    cmaps: tuple[str, ...] = _DEFAULT_CMAPS,
) -> dict[str, Path]:
    """Plot one PNG per group from a ``{group_name: array}`` dict.

    Saves to ``<out_dir>/<label>_<group>.png`` and returns the dict of
    written paths.
    """
    out_dir = Path(out_dir)
    written: dict[str, Path] = {}
    for i, (name, arr) in enumerate(arrays.items()):
        cmap = cmaps[i % len(cmaps)]
        path = plot_raster(
            arr,
            cmap=cmap,
            title=f"{label} ({name})",
            save_path=out_dir / f"{label}_{name}.png",
        )
        if path is not None:
            written[f"{label}_{name}"] = path
    return written
