from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from d_health.config.groups import PopulationGroup

logger = logging.getLogger(__name__)

# Default risk-class edges: 5 equal bins spanning probability [0, 1].
DEFAULT_RISK_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def bin_population_by_risk(
    risks: dict[str, np.ndarray],
    population: xr.DataArray,
    groups: list[PopulationGroup],
    *,
    edges: tuple[float, ...] = DEFAULT_RISK_EDGES,
) -> dict[str, np.ndarray]:
    """Population in each risk-class bin, per group.

    For each group, walks the half-open bins ``[edges[i], edges[i+1])`` (the
    last one is closed on the right so risk == 1 lands somewhere) and sums the
    group's population in cells whose risk falls into that bin. NaN risks are
    skipped — they correspond to dry cells with no exposure.

    Returns ``{group_name: ndarray(len(edges)-1,)}`` — a population histogram
    over the risk bins, per group.
    """
    if len(edges) < 2:
        raise ValueError(f"edges must have at least 2 entries; got {edges}")

    out: dict[str, np.ndarray] = {}
    n_bins = len(edges) - 1
    for g in groups:
        risk = risks[g.name]
        pop = np.nan_to_num(population.sel(group=g.name).values, nan=0.0)
        counts = np.zeros(n_bins, dtype=np.float64)
        for i in range(n_bins):
            lo, hi = edges[i], edges[i + 1]
            if i == n_bins - 1:
                mask = (risk >= lo) & (risk <= hi)
            else:
                mask = (risk >= lo) & (risk < hi)
            counts[i] = float(np.sum(pop * mask))
        out[g.name] = counts
    return out


def plot_risk_class_histogram(
    counts: dict[str, np.ndarray],
    *,
    edges: tuple[float, ...] = DEFAULT_RISK_EDGES,
    save_path: Path | None = None,
    show: bool = False,
) -> Path | None:
    """Grouped bar chart of population per risk-class bin, one bar series per group."""
    if not counts:
        logger.warning("plot_risk_class_histogram: empty counts dict, skipping")
        return None

    n_bins = len(edges) - 1
    n_groups = len(counts)
    index = np.arange(n_bins)
    bar_width = 0.8 / n_groups

    fig, ax = plt.subplots(figsize=(10, 6))
    for i, (name, vals) in enumerate(counts.items()):
        ax.bar(index + i * bar_width, vals, bar_width, label=name)

    ax.set_xlabel("Risk class")
    ax.set_ylabel("Population count")
    ax.set_title("Population count in risk classes")
    ax.set_xticks(index + bar_width * (n_groups - 1) / 2)
    ax.set_xticklabels(
        [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(n_bins)]
    )
    ax.legend()

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
