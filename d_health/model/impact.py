from __future__ import annotations

import logging

import numpy as np
import xarray as xr

from d_health.config.groups import PopulationGroup

logger = logging.getLogger(__name__)


def calc_infected_pop_per_group(
    risks: dict[str, np.ndarray],
    population: xr.DataArray,
    groups: list[PopulationGroup],
) -> dict[str, np.ndarray]:
    """Per-group infected counts: ``risk × population layer``.

    ``population`` is the full array ``(group, rows, cols)`` with a labelled
    ``group`` dimension. Each group's ``name`` selects the layer to multiply.
    NaN risks (cells with no exposure) produce NaN counts.
    """
    out: dict[str, np.ndarray] = {}
    for g in groups:
        band = population.sel(group=g.name).values
        out[g.name] = risks[g.name] * band
    return out
