from __future__ import annotations

import logging

import numpy as np

from d_health.config.emissions import CountryIndicators, EmissionsConfig

logger = logging.getLogger(__name__)


def compute_emissions(
    popdens: np.ndarray,
    urban_rural: np.ndarray,
    country: CountryIndicators,
    cfg: EmissionsConfig,
) -> np.ndarray:
    """Per-cell E. coli emission load, before any flood gating.

    The emission of each grid cell is the population living there scaled by
    three factors:

        emissions = popdens × per_capita_rate × per_cell_sanitation_factor × weight_factor

    ``per_cell_sanitation_factor`` is ``urban_eff`` in urban cells,
    ``rural_eff`` in rural cells, and ``1.0`` elsewhere. ``urban_eff`` /
    ``rural_eff`` capture how much of the baseline emission survives the
    country's sanitation infrastructure: they are the dot product of the
    country-level coverage of each sanitation tier (as a fraction) with that
    tier's retained-fraction multiplier:

        urban_eff = Σᵢ (country.sanitation[i].urban / 100) × cfg.sanitation_reductions[i].urban_reduction_factor
        rural_eff = analogously

    ``weight_factor`` scales emissions down as GDP per capita rises (a proxy
    for better infrastructure): ``max(floor, intercept - gdp / divisor)`` — see
    :class:`d_health.config.emissions.GDPWeight`.

    The cross-config invariant that every ``country.sanitation`` tier name has
    a matching ``cfg.sanitation_reductions`` entry is enforced at config load
    time by ``RunConfig`` — this function does not re-check it.

    Notes
    -----
    No flood term: flood gating happens implicitly downstream in
    ``calc_pathogen_conc`` via division by ``flood × cell_area × M3_TO_HL``.

    ``urban_rural`` follows the GHS-SMOD-derived convention used by
    ``preprocessing.smod.get_smod_data``:
    ``1 = urban``, ``2 = rural``, ``0 = nodata``.
    """
    reductions_by_name = {r.name: r for r in cfg.sanitation_reductions}

    urban_eff = sum(
        s.urban / 100.0 * reductions_by_name[s.name].urban_reduction_factor
        for s in country.sanitation
    )
    rural_eff = sum(
        s.rural / 100.0 * reductions_by_name[s.name].rural_reduction_factor
        for s in country.sanitation
    )
    logger.debug(
        "Sanitation factors for %s: urban=%.4f rural=%.4f",
        country.country_code,
        urban_eff,
        rural_eff,
    )

    sani = np.ones_like(popdens, dtype=np.float64)
    sani[urban_rural == 1] = urban_eff
    sani[urban_rural == 2] = rural_eff

    gw = cfg.gdp_weight
    weight = max(gw.floor, gw.intercept - country.gdp_per_capita / gw.divisor)
    logger.debug(
        "GDP weight factor (GDP=%.0f): %.4f",
        country.gdp_per_capita,
        weight,
    )

    return popdens.astype(np.float64) * cfg.per_capita_ecoli_rate * sani * weight
