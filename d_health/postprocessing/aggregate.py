from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def per_group_totals(infected: dict[str, np.ndarray]) -> dict[str, float]:
    """Sum each group's infected raster, NaN-safe.

    Returns one total per population group, keyed ``f"infected_{group}"``
    (e.g. ``"infected_adults"``) — the totals the CLI prints and the pipeline
    reports.
    """
    return {f"infected_{name}": float(np.nansum(arr)) for name, arr in infected.items()}
