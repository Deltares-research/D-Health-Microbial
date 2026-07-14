from __future__ import annotations

import logging

import numpy as np

from d_health.geo import get_cell_area

logger = logging.getLogger(__name__)

# Unit-conversion factor from cubic metres (cell_area_m² × depth_m) to 100-mL
# units: 1 m³ = 1000 L = 10 000 × 100 mL. Single source of truth — the
# pipeline no longer surfaces this as user config because it falls out of unit
# conversion, not from any literature parameter.
M3_TO_HL = 10000


def calc_pathogen_conc(
    flood_meta: dict,
    flood: np.ndarray,
    emissions: np.ndarray,
    *,
    factor: int = M3_TO_HL,
) -> np.ndarray:
    """Per-cell pathogen concentration (CFU per 100 mL of floodwater).

        EcoliConc = emissions / (cell_area × flood × 10000)

    ``flood`` is flood depth in metres under the positive-depth convention
    (``> 0`` flooded, ``0`` or ``NaN`` dry). Dry cells hold no floodwater, so a
    concentration is not defined there: they are returned as ``NaN``, the
    package-wide nodata convention, which then propagates through the
    downstream dose / risk / infected steps.

    The dry-cell gate is applied explicitly rather than left to the arithmetic.
    Dividing by a depth of ``0`` yields ``+inf``, and an ``inf`` concentration
    turns into an ``inf`` dose and a *risk of 1.0* — a cell of dry land
    reporting certain infection. That only stayed harmless because every
    bundled population group starts at ``min_depth = 0.1``, i.e. the ``inf``
    was masked by a default rather than by the code. Gating here makes the
    convention true by construction, independent of how groups are configured.
    """
    cell_area = get_cell_area(flood_meta)
    with np.errstate(divide="ignore", invalid="ignore"):
        conc = emissions / (cell_area * flood * factor)

    # `flood > 0` is False for NaN as well as for <= 0, so this catches both.
    return np.where(flood > 0.0, conc, np.nan)
