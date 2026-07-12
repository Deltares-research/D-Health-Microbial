from __future__ import annotations

import logging

import numpy as np

from d_health.config.emissions import CountryIndicators, EmissionsConfig

logger = logging.getLogger(__name__)

# Above this share of unclassified urban/rural cells, the sanitation fallback is
# driving enough of the map that the user should be told loudly.
_NODATA_WARN_FRACTION = 0.20


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
    ``rural_eff`` in rural cells, and — in cells the urban/rural raster leaves
    unclassified — whatever ``cfg.nodata_sanitation`` selects (default
    ``"none"``, i.e. factor ``1.0`` = no sanitation infrastructure; see
    :data:`d_health.config.emissions.NodataSanitation`). The unclassified share
    is logged, and warned about past 20%, because that fallback is a
    maximum-emission assumption applied to the least-known cells.

    ``urban_eff`` / ``rural_eff`` capture how much of the baseline emission
    survives the country's sanitation infrastructure: they are the dot product
    of the country-level coverage of each sanitation tier (as a fraction) with
    that tier's retained-fraction multiplier:

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

    urban_mask = urban_rural == 1
    rural_mask = urban_rural == 2
    nodata_mask = ~(urban_mask | rural_mask)

    fallback = {
        "none": 1.0,
        "urban": urban_eff,
        "rural": rural_eff,
        "nan": np.nan,
    }[cfg.nodata_sanitation]

    sani = np.full(popdens.shape, fallback, dtype=np.float64)
    sani[urban_mask] = urban_eff
    sani[rural_mask] = rural_eff

    n_nodata = int(nodata_mask.sum())
    if n_nodata:
        share = n_nodata / nodata_mask.size
        log = logger.warning if share > _NODATA_WARN_FRACTION else logger.info
        log(
            "urban_rural: %d of %d cells (%.1f%%) unclassified — applying "
            "nodata_sanitation=%r (factor %s)",
            n_nodata,
            nodata_mask.size,
            share * 100.0,
            cfg.nodata_sanitation,
            fallback,
        )

    gw = cfg.gdp_weight
    weight = max(gw.floor, gw.intercept - country.gdp_per_capita / gw.divisor)
    logger.debug(
        "GDP weight factor (GDP=%.0f): %.4f",
        country.gdp_per_capita,
        weight,
    )

    return popdens.astype(np.float64) * cfg.per_capita_ecoli_rate * sani * weight
