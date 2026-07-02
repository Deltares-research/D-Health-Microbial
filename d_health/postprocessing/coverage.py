from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import xarray as xr

from d_health.config.emissions import EmissionsConfig
from d_health.config.groups import PopulationGroup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoverageBreakdown:
    """Population totals split by flooded vs dry, with per-flood-class breakdown.

    All entries are ``{group_name → count}``; the special key ``"total"`` is
    derived from ``EmissionsConfig.total_population_group``. ``per_class`` keys
    are the flood-class integers from
    :func:`d_health.postprocessing.flood_classes.compute_flood_classes`
    (``0`` = dry, ``1`` = first activity band, etc).
    """

    total: dict[str, float] = field(default_factory=dict)
    flooded: dict[str, float] = field(default_factory=dict)
    dry: dict[str, float] = field(default_factory=dict)
    per_class: dict[int, dict[str, float]] = field(default_factory=dict)


def _is_flooded(flood: np.ndarray) -> np.ndarray:
    """Boolean mask of flooded cells under the positive-depth convention."""
    return np.where(np.isnan(flood), False, flood > 0.0)


def flooded_dry_stats(
    flood: np.ndarray,
    population: xr.DataArray,
    groups: list[PopulationGroup],
    emissions_cfg: EmissionsConfig,
    *,
    flood_classes: np.ndarray | None = None,
) -> CoverageBreakdown:
    """Population totals across the AOI, split by flooded vs dry, per group plus total.

    If ``flood_classes`` is supplied (an integer raster from
    :func:`compute_flood_classes`), also breaks the flooded count down by
    class.
    """
    flooded = _is_flooded(flood)

    pop_total = np.nan_to_num(
        population.sel(group=emissions_cfg.total_population_group).values, nan=0.0
    )

    out = CoverageBreakdown()
    out.total["total"] = float(pop_total.sum())
    out.flooded["total"] = float((pop_total * flooded).sum())
    out.dry["total"] = float((pop_total * ~flooded).sum())

    for g in groups:
        pop_g = np.nan_to_num(population.sel(group=g.name).values, nan=0.0)
        out.total[g.name] = float(pop_g.sum())
        out.flooded[g.name] = float((pop_g * flooded).sum())
        out.dry[g.name] = float((pop_g * ~flooded).sum())

    if flood_classes is not None:
        unique = [int(c) for c in np.unique(flood_classes) if c != 0]
        for cls in unique:
            mask = flood_classes == cls
            entry: dict[str, float] = {
                "total": float((pop_total * mask).sum()),
            }
            for g in groups:
                pop_g = np.nan_to_num(population.sel(group=g.name).values, nan=0.0)
                entry[g.name] = float((pop_g * mask).sum())
            out.per_class[cls] = entry

    return out


def log_coverage(stats: CoverageBreakdown) -> None:
    """Print a human-readable coverage summary to the logger at INFO level."""
    total = stats.total.get("total", 0.0)
    flooded = stats.flooded.get("total", 0.0)
    dry = stats.dry.get("total", 0.0)
    pct = (flooded / total * 100.0) if total else 0.0

    logger.info("Total inhabitants:                 %d", round(total))
    logger.info("In flooded area:                   %d (%.0f%%)", round(flooded), pct)
    logger.info("In dry area:                       %d (%.0f%%)", round(dry), 100.0 - pct)

    for name in stats.flooded:
        if name == "total":
            continue
        n_total = stats.total[name]
        n_flooded = stats.flooded[name]
        share = (n_flooded / n_total * 100.0) if n_total else 0.0
        logger.info(
            "  %-22s in flooded area: %d (%.0f%%)",
            name, round(n_flooded), share,
        )

    for cls, entry in sorted(stats.per_class.items()):
        cls_total = entry.get("total", 0.0)
        share = (cls_total / total * 100.0) if total else 0.0
        logger.info(
            "Flood class %d: %d inhabitants (%.0f%%)",
            cls, round(cls_total), share,
        )
