from __future__ import annotations

import logging

import numpy as np

from d_health.config.groups import PopulationGroup

logger = logging.getLogger(__name__)


def calc_dose_per_group(
    depth: np.ndarray,
    pathogen_conc: np.ndarray,
    group: PopulationGroup,
    event_in_hours: float = 1.0,
) -> np.ndarray:
    """Per-cell ingested dose (CFU per event) for one population group.

    ``depth`` is flood depth in metres under the positive-depth convention
    (``> 0`` flooded). Walks the group's sorted depth thresholds and assigns
    each cell the ingestion of the band whose ``min_depth`` range the cell
    falls into. Cells with ``depth < depth_thresholds[0].min_depth`` (including
    dry cells) get NaN — no exposure.

    ``pathogen_conc`` is in CFU per 100 mL; ingestion is in mL/h, normalised
    from ``ml/event`` rates by ``event_in_hours``. Result is CFU per event.
    """
    out = np.full_like(depth, np.nan, dtype=np.float64)

    # Build (lower, upper) bands from sorted min_depths. Last band's upper is +inf.
    thresholds = group.depth_thresholds
    n = len(thresholds)
    for i, thr in enumerate(thresholds):
        lower = thr.min_depth
        upper = thresholds[i + 1].min_depth if i + 1 < n else np.inf
        if i + 1 < n:
            mask = (depth >= lower) & (depth < upper)
        else:
            mask = depth >= lower
        # Ingestion in mL/h, normalised; divide by 100 because conc is per 100 mL.
        ing_per_h = thr.ingestion_ml_per_h(event_in_hours)
        out[mask] = ing_per_h * pathogen_conc[mask] / 100.0
    return out


def calc_dose_for_groups(
    depth: np.ndarray,
    pathogen_conc: np.ndarray,
    groups: list[PopulationGroup],
    event_in_hours: float = 1.0,
) -> dict[str, np.ndarray]:
    """Convenience wrapper returning a dict keyed by group name."""
    return {
        g.name: calc_dose_per_group(depth, pathogen_conc, g, event_in_hours)
        for g in groups
    }
