"""Regression: dry land must never report infection.

The pipeline gates itself to flooded cells by dividing by flood depth in
``calc_pathogen_conc``. At depth 0 that division yields ``+inf``, and an ``inf``
concentration flows through to an ``inf`` dose and a *risk of 1.0* — every
person in a dry cell counted as infected.

That never fired in practice only because every bundled population group starts
at ``min_depth = 0.1``, so the lowest depth band excluded the dry cells before
the ``inf`` could be used. The ``inf`` was masked by a default, not by the code:
``DepthThreshold.min_depth`` was declared ``ge=0.0``, so ``min_depth = 0.0`` was
a *valid config* that turned dry land into a 100%-infection zone, silently.

Two layers now prevent it, and this module tests both:

1. ``calc_pathogen_conc`` NaNs dry cells explicitly, so the convention holds by
   construction whatever the groups are configured to do.
2. ``PopulationGroup`` rejects a lowest threshold at ``min_depth <= 0``, so the
   config that used to trigger it is now a load-time error with a readable
   message.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from d_health.config.groups import DepthThreshold, PopulationGroup
from d_health.model.concentration import calc_pathogen_conc
from d_health.model.emissions import compute_emissions
from d_health.model.exposure import calc_dose_for_groups
from d_health.model.impact import calc_infected_pop_per_group
from d_health.model.risk import calc_infection_risk_beta_poisson


def test_min_depth_zero_is_rejected_at_config_time():
    """Layer 2: a group exposed at zero depth is not a valid config."""
    with pytest.raises(ValidationError, match="min_depth > 0"):
        PopulationGroup(
            name="waders",
            depth_thresholds=[
                DepthThreshold(name="wading", min_depth=0.0, ing=10.0, unit="ml/h")
            ],
        )


def test_negative_min_depth_is_rejected_at_config_time():
    with pytest.raises(ValidationError):
        PopulationGroup(
            name="waders",
            depth_thresholds=[
                DepthThreshold(name="wading", min_depth=-1.0, ing=10.0, unit="ml/h")
            ],
        )


def test_dry_cells_stay_unexposed_even_at_the_lowest_possible_threshold(
    small_meta, population_16x16, default_emissions_cfg, default_country
):
    """Layer 1: even a group thresholded as low as the schema allows, a dry cell
    is NaN — not a certain infection.

    This is the end-to-end shape of the original bug: build the smallest legal
    ``min_depth``, run the full emissions → conc → dose → risk → infected chain
    over a grid that is half dry, and assert the dry half contributes nothing.
    """
    flood = np.zeros((16, 16), dtype=np.float32)
    flood[8:, :] = 1.0  # bottom half flooded, top half bone dry
    urban_rural = np.ones((16, 16), dtype=np.int8)

    # The lowest threshold the validator will now accept. Before the fix, the
    # equivalent config (min_depth=0.0) marked every dry cell as fully infected.
    groups = [
        PopulationGroup(
            name="adults",
            depth_thresholds=[
                DepthThreshold(name="wading", min_depth=1e-9, ing=10.0, unit="ml/h")
            ],
        )
    ]

    popdens = population_16x16.sel(group="total").values
    emissions = compute_emissions(
        popdens=popdens,
        urban_rural=urban_rural,
        country=default_country,
        cfg=default_emissions_cfg,
    )
    conc = calc_pathogen_conc(small_meta, flood, emissions)
    doses = calc_dose_for_groups(flood, conc, groups, 1.0)
    risks = {
        n: calc_infection_risk_beta_poisson(d, 0.373, 39.71) for n, d in doses.items()
    }
    infected = calc_infected_pop_per_group(risks, population_16x16, groups)

    dry = slice(0, 8)
    assert np.isnan(conc[dry]).all(), "dry cells must have no concentration"
    assert np.isnan(doses["adults"][dry]).all(), "dry cells must have no dose"
    assert np.isnan(risks["adults"][dry]).all(), "dry cells must have no risk"
    assert np.isnan(infected["adults"][dry]).all(), "nobody is infected on dry land"

    # And nothing anywhere is inf: an inf risk would silently be 1.0.
    for arr in (conc, doses["adults"], risks["adults"], infected["adults"]):
        assert not np.isinf(arr).any()

    # The flooded half still works — this is a gate, not a mute button.
    wet = slice(8, 16)
    assert np.isfinite(infected["adults"][wet]).all()
    assert float(np.nansum(infected["adults"])) > 0.0
