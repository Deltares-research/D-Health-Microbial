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
    (``> 0`` flooded, ``0`` or ``NaN`` dry). The division by ``flood`` is what
    implicitly gates the pipeline to flooded cells: dry cells produce ``inf``
    (depth ``0``) or ``NaN`` (depth ``NaN``) concentration, which propagates as
    NaN through the downstream dose / risk calculations.
    """
    cell_area = get_cell_area(flood_meta)
    with np.errstate(divide="ignore", invalid="ignore"):
        conc = emissions / (cell_area * flood * factor)
    return conc
