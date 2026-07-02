from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap

from d_health.config.groups import PopulationGroup

logger = logging.getLogger(__name__)


def derive_flood_class_edges(groups: list[PopulationGroup]) -> tuple[float, ...]:
    """Sorted union of ``DepthThreshold.min_depth`` across every group.

    For the default adults/children groups (adults: 0.1, 1.5; children:
    0.1, 0.5) this returns ``(0.1, 0.5, 1.5)``.
    """
    edges: set[float] = set()
    for g in groups:
        for the in g.depth_thresholds:
            edges.add(float(the.min_depth))
    return tuple(sorted(edges))


def compute_flood_classes(
    flood: np.ndarray,
    groups: list[PopulationGroup],
) -> np.ndarray:
    """Integer raster classifying each cell by flood-depth band.

    Class codes:

    - ``0`` — dry (depth ``≤ 0`` or NaN).
    - ``1`` — *minimum flooded* (``0 < depth < edges[0]``): wet but below the
      lowest activity threshold, so no group is exposed there.
    - ``2..n+1`` — depth in ``[edges[i-1], edges[i])`` for ``n`` activity
      bands. The last class is open-ended (``≥ edges[-1]``).

    For the default adults/children groups (edges 0.1, 0.5, 1.5) this gives
    five classes (0 = dry, 1 = minimum flooded, 2 = all wading, 3 = children
    swim/adults wade, 4 = both swimming). Adding a new group with different
    thresholds automatically refines the classification.
    """
    edges = derive_flood_class_edges(groups)
    if not edges:
        raise ValueError(
            "compute_flood_classes: at least one activity must define min_depth"
        )

    out = np.zeros_like(flood, dtype=np.int16)
    # NaN-safe: a cell is "above edges[i]" only if it's finite.
    finite = np.where(np.isnan(flood), 0.0, flood)

    # Class 1: wet but below the first activity threshold (no exposure).
    out[(finite > 0) & (finite < edges[0])] = 1

    # Classes 2..n+1: activity bands. Walk in order; later edges overwrite
    # earlier ones, so the last band that contains a cell wins.
    for i, edge in enumerate(edges):
        out[finite >= edge] = i + 2

    # Force class 0 for dry / NaN cells.
    out[np.isnan(flood)] = 0
    out[flood <= 0] = 0
    return out


def flood_class_labels(groups: list[PopulationGroup]) -> tuple[str, ...]:
    """Human-readable labels for each flood class (in class-code order, 1..n+1).

    The first label is ``"minimum flooded"`` (class 1, below the lowest
    activity threshold). Subsequent labels describe each activity band as
    ``"[lo, hi) m"`` or ``"≥ lo m"`` for the open-ended top band.
    """
    edges = derive_flood_class_edges(groups)
    labels: list[str] = [f"minimum flooded (0, {edges[0]:.2f}) m"]
    for i, edge in enumerate(edges):
        if i + 1 < len(edges):
            upper = edges[i + 1]
            labels.append(f"[{edge:.2f}, {upper:.2f}) m")
        else:
            labels.append(f"≥ {edge:.2f} m")
    return tuple(labels)


# 4-colour ramp: green/yellow/orange/red by increasing flood severity.
_DEFAULT_PALETTE: tuple[str, ...] = ("green", "yellow", "orange", "red")


def plot_flood_classes(
    flood_classes: np.ndarray,
    groups: list[PopulationGroup],
    *,
    save_path: Path | None = None,
    show: bool = False,
    palette: tuple[str, ...] = _DEFAULT_PALETTE,
) -> Path | None:
    """Colour-coded plot of the flood-class raster, with class labels in the colour bar."""
    labels = flood_class_labels(groups)
    n = len(labels)
    if n == 0:
        logger.warning("plot_flood_classes: no classes derived, skipping")
        return None

    # Cycle the palette if more classes than colours.
    colors = [palette[i % len(palette)] for i in range(n)]
    cmap = ListedColormap(colors)
    boundaries = [i + 0.5 for i in range(n + 1)]
    boundaries[0] = 0.5
    norm = BoundaryNorm(boundaries, cmap.N)

    masked = np.ma.masked_where(flood_classes == 0, flood_classes)

    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(masked, cmap=cmap, norm=norm)
    cbar = fig.colorbar(im, ax=ax, ticks=range(1, n + 1), boundaries=boundaries)
    cbar.ax.set_yticklabels(labels)
    ax.set_title("Flood depth classes")

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
