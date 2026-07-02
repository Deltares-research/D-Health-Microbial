from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from d_health.postprocessing.coverage import CoverageBreakdown


class ModelOutputs(BaseModel):
    """Result of one ``run_model`` call.

    Keys of ``doses`` / ``risks`` / ``infected`` / ``risk_class_counts`` are
    the population group names from ``RunConfig.settings.population_groups``.
    ``totals`` is a flat dict of summary scalars (one ``infected_<group>``
    per group); ``paths`` maps a logical artifact name (e.g. ``"emissions"``,
    ``"infected_adults"``, ``"flood_classes"``, ``"risk_histogram"``) to its
    on-disk output path; ``meta`` is the common-grid georeferencing dict.

    ``flood_classes`` is a same-shape integer raster derived from the union
    of population-group activity thresholds (``0`` = dry, ``1..n`` = deeper
    bands — see :func:`d_health.postprocessing.compute_flood_classes`).
    ``coverage`` holds the flooded-vs-dry breakdown and
    per-class population counts. ``risk_class_counts`` holds the per-group
    histogram of population over risk bins.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    emissions: np.ndarray
    pathogen_conc: np.ndarray
    doses: dict[str, np.ndarray]
    risks: dict[str, np.ndarray]
    infected: dict[str, np.ndarray]
    totals: dict[str, float]
    paths: dict[str, Path]
    meta: dict[str, Any]
    flood_classes: np.ndarray | None = None
    coverage: CoverageBreakdown | None = None
    risk_class_counts: dict[str, np.ndarray] = Field(default_factory=dict)
    risk_class_edges: tuple[float, ...] = ()
