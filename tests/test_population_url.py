"""WorldPopConfig layout selection and URL/filename construction.

These tests pin both supported product layouts so a change to the default
(``global1_2000_2020`` — the constrained 2020 product) or to the URL
convention is caught without hitting the network.
"""
from __future__ import annotations

from d_health.config.preprocessing import (
    ADULT_AGE_BINS,
    ADULT_AGE_BINS_G2,
    ADULT_AGE_BINS_LEGACY,
    CHILD_AGE_BINS,
    CHILD_AGE_BINS_G2,
    CHILD_AGE_BINS_LEGACY,
    WorldPopConfig,
)
from d_health.preprocessing.population import _build_url


def test_default_is_legacy_2000_2020_product():
    cfg = WorldPopConfig()
    assert cfg.layout == "global1_2000_2020"
    assert cfg.constrained is True
    assert cfg.series == "Global_2000_2020_Constrained"
    # Unpadded child codes and adults capped at 80.
    assert cfg.child_age_bins == CHILD_AGE_BINS_LEGACY == ("0", "1", "5")
    assert cfg.adult_age_bins == ADULT_AGE_BINS_LEGACY
    assert cfg.adult_age_bins[-1] == "80"
    # Back-compat module aliases follow the default product.
    assert CHILD_AGE_BINS == CHILD_AGE_BINS_LEGACY
    assert ADULT_AGE_BINS == ADULT_AGE_BINS_LEGACY


def test_legacy_constrained_url_and_filename():
    cfg = WorldPopConfig()
    child = _build_url("MOZ", 2020, cfg.child_age_bins[0], "f", cfg)
    adult = _build_url("MOZ", 2020, cfg.adult_age_bins[-1], "m", cfg)
    assert child == (
        "https://data.worldpop.org/GIS/AgeSex_structures/"
        "Global_2000_2020_Constrained/2020/MOZ/moz_f_0_2020_constrained.tif"
    )
    assert adult.endswith("/MOZ/moz_m_80_2020_constrained.tif")


def test_legacy_unconstrained_drops_suffix_and_series():
    cfg = WorldPopConfig(constrained=False)
    assert cfg.series == "Global_2000_2020"
    url = _build_url("MOZ", 2020, "5", "f", cfg)
    assert url == (
        "https://data.worldpop.org/GIS/AgeSex_structures/"
        "Global_2000_2020/2020/MOZ/moz_f_5_2020.tif"
    )


def test_global2_layout_url_and_filename():
    cfg = WorldPopConfig(layout="global2_2015_2030")
    assert cfg.series == "Global_2015_2030"
    assert cfg.child_age_bins == CHILD_AGE_BINS_G2 == ("00", "01", "05")
    assert cfg.adult_age_bins == ADULT_AGE_BINS_G2
    assert cfg.adult_age_bins[-1] == "90"
    child = _build_url("MOZ", 2020, cfg.child_age_bins[0], "f", cfg)
    assert child == (
        "https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/"
        "R2025A/2020/MOZ/v1/100m/constrained/"
        "moz_f_00_2020_CN_100m_R2025A_v1.tif"
    )


def test_global2_unconstrained_type_tokens():
    cfg = WorldPopConfig(layout="global2_2015_2030", constrained=False)
    assert cfg.type_code == "UC"
    assert cfg.type_dir == "unconstrained"
    url = _build_url("MOZ", 2020, "00", "f", cfg)
    assert "/unconstrained/" in url
    assert "_UC_100m_R2025A_v1.tif" in url
