"""compute_emissions formula + no-reduction sanity.

The cross-config sanitation-name-coverage check is enforced at config load by
``RunConfig`` (see
``test_validators.test_runconfig_missing_sanitation_reduction_raises``), not by
``compute_emissions`` — so these tests can assume a consistent config.
"""

from __future__ import annotations

import numpy as np
import pytest

from d_health.config.emissions import (
    EmissionsConfig,
    GDPWeight,
    SanitationReduction,
)
from d_health.model.emissions import compute_emissions


def test_emissions_matches_reference_formula(default_emissions_cfg, default_country):
    """One urban cell + one rural cell, hand-computed reference."""
    popdens = np.array([[100.0, 200.0]], dtype=np.float64)
    urban_rural = np.array([[1, 2]], dtype=np.int8)

    out = compute_emissions(
        popdens=popdens,
        urban_rural=urban_rural,
        country=default_country,
        cfg=default_emissions_cfg,
    )

    # Expected per-region effective factor:
    # urban: 0.80*0.10 + 0.10*0.25 + 0.05*0.70 + 0.05*1.00 = 0.08 + 0.025 + 0.035 + 0.05 = 0.190
    # rural: 0.50*0.10 + 0.20*0.25 + 0.20*0.30 + 0.10*1.00 = 0.05 + 0.05 + 0.06 + 0.10  = 0.260
    urban_eff = 0.80 * 0.10 + 0.10 * 0.25 + 0.05 * 0.70 + 0.05 * 1.00
    rural_eff = 0.50 * 0.10 + 0.20 * 0.25 + 0.20 * 0.30 + 0.10 * 1.00
    # weight = max(0.5, 1.0 - 7000/80000) = max(0.5, 0.9125) = 0.9125
    weight = max(0.5, 1.0 - 7000.0 / 80000.0)
    assert weight == 0.9125

    expected_urban = 100.0 * 1.0e9 * urban_eff * weight
    expected_rural = 200.0 * 1.0e9 * rural_eff * weight

    assert np.isclose(out[0, 0], expected_urban)
    assert np.isclose(out[0, 1], expected_rural)


def test_nodata_sanitation_default_reproduces_historical_behaviour(
    default_emissions_cfg, default_country
):
    """The default (``"none"``) must leave unclassified cells at factor 1.0.

    That is the *maximum-emission* assumption — the same factor the "None"
    sanitation tier gets — applied to the cells we know least about. It is the
    model's historical behaviour, so it stays the default; this test pins it so
    the choice can't drift silently.
    """
    assert default_emissions_cfg.nodata_sanitation == "none"

    popdens = np.array([[100.0, 100.0, 100.0]], dtype=np.float64)
    urban_rural = np.array([[1, 2, 0]], dtype=np.int8)  # urban, rural, nodata

    out = compute_emissions(
        popdens=popdens,
        urban_rural=urban_rural,
        country=default_country,
        cfg=default_emissions_cfg,
    )

    weight = max(0.5, 1.0 - 7000.0 / 80000.0)
    assert np.isclose(out[0, 2], 100.0 * 1.0e9 * 1.0 * weight)
    # The nodata cell out-emits the urban one by the reciprocal of urban_eff.
    assert out[0, 2] > out[0, 0]


@pytest.mark.parametrize(
    "mode, expected_factor",
    [
        ("none", 1.0),
        ("urban", 0.80 * 0.10 + 0.10 * 0.25 + 0.05 * 0.70 + 0.05 * 1.00),
        ("rural", 0.50 * 0.10 + 0.20 * 0.25 + 0.20 * 0.30 + 0.10 * 1.00),
    ],
)
def test_nodata_sanitation_modes(
    default_emissions_cfg, default_country, mode, expected_factor
):
    """Each fallback mode applies its stated factor to unclassified cells."""
    cfg = default_emissions_cfg.model_copy(update={"nodata_sanitation": mode})
    popdens = np.array([[100.0]], dtype=np.float64)
    urban_rural = np.array([[0]], dtype=np.int8)  # unclassified

    out = compute_emissions(
        popdens=popdens, urban_rural=urban_rural, country=default_country, cfg=cfg
    )

    weight = max(0.5, 1.0 - 7000.0 / 80000.0)
    assert np.isclose(out[0, 0], 100.0 * 1.0e9 * expected_factor * weight)


def test_nodata_sanitation_nan_excludes_the_cell(
    default_emissions_cfg, default_country
):
    """``"nan"`` drops unclassified cells from the emissions field entirely."""
    cfg = default_emissions_cfg.model_copy(update={"nodata_sanitation": "nan"})
    popdens = np.array([[100.0, 100.0]], dtype=np.float64)
    urban_rural = np.array([[1, 0]], dtype=np.int8)

    out = compute_emissions(
        popdens=popdens, urban_rural=urban_rural, country=default_country, cfg=cfg
    )

    assert np.isfinite(out[0, 0])
    assert np.isnan(out[0, 1])


def test_unclassified_share_is_warned_about(
    default_emissions_cfg, default_country, caplog
):
    """A mostly-unclassified urban/rural raster must not pass quietly.

    The fallback is a modelling assumption; if it is driving most of the map, the
    user needs to know before they read the numbers.
    """
    popdens = np.full((10, 10), 100.0, dtype=np.float64)
    urban_rural = np.zeros((10, 10), dtype=np.int8)  # 100% unclassified

    with caplog.at_level("WARNING"):
        compute_emissions(
            popdens=popdens,
            urban_rural=urban_rural,
            country=default_country,
            cfg=default_emissions_cfg,
        )

    assert "unclassified" in caplog.text


def test_emissions_no_sanitation_reduction(default_country):
    """All retained-fraction = 1.0 → output is plain popdens × rate × weight regardless of region."""
    cfg = EmissionsConfig(
        per_capita_ecoli_rate=1.0e9,
        total_population_group="total",
        gdp_weight=GDPWeight(),
        sanitation_reductions=[
            SanitationReduction(
                name=s.name, urban_reduction_factor=1.0, rural_reduction_factor=1.0
            )
            for s in default_country.sanitation
        ],
    )
    popdens = np.array([[100.0, 100.0, 100.0]])
    urban_rural = np.array([[1, 2, 0]], dtype=np.int8)
    out = compute_emissions(
        popdens=popdens, urban_rural=urban_rural, country=default_country, cfg=cfg
    )
    weight = max(0.5, 1.0 - 7000.0 / 80000.0)
    expected = 100.0 * 1.0e9 * weight
    assert np.allclose(out, expected)
