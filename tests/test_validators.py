"""Tests #6-7: Pydantic validators on CountryIndicators, PopulationGroup,
GDPWeight, WDIConfig, and the cross-config sanitation-name check on RunConfig.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from d_health.config.emissions import (
    CountryIndicators,
    EmissionsConfig,
    GDPWeight,
    SanitationLevel,
    SanitationReduction,
)
from d_health.config.groups import DepthThreshold, PopulationGroup
from d_health.config.preprocessing import WDIConfig
from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
    SettingsConfig,
)


def _run_config(exposure_country_path, settings, tmp_path):
    """Build a RunConfig whose exposure points at a written country TOML."""
    return RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "p.tif",
            urban_rural=tmp_path / "u.tif",
            country_indicators=exposure_country_path,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "x.tif"),
        output=OutputConfig(out_dir=tmp_path / "out", plots=False),
        settings=settings,
    )


def test_sanitation_sum_validator_urban_too_low():
    with pytest.raises(ValidationError, match="urban must sum to 100"):
        CountryIndicators(
            country_code="XXX",
            gdp_per_capita=1000.0,
            sanitation=[
                SanitationLevel(name="Safe",  urban=50.0, rural=50.0),
                SanitationLevel(name="Basic", urban=40.0, rural=50.0),  # urban sums to 90
            ],
        )


def test_sanitation_sum_validator_rural_too_high():
    with pytest.raises(ValidationError, match="rural must sum to 100"):
        CountryIndicators(
            country_code="XXX",
            gdp_per_capita=1000.0,
            sanitation=[
                SanitationLevel(name="Safe",  urban=50.0, rural=60.0),
                SanitationLevel(name="Basic", urban=50.0, rural=50.0),  # rural sums to 110
            ],
        )


def test_country_code_must_be_iso3():
    with pytest.raises(ValidationError, match="country_code"):
        CountryIndicators(
            country_code="sur",  # lowercase not allowed
            gdp_per_capita=1000.0,
            sanitation=[SanitationLevel(name="Safe", urban=100.0, rural=100.0)],
        )


def test_depth_thresholds_out_of_order_raises():
    with pytest.raises(ValidationError, match="sorted ascending"):
        PopulationGroup(
            name="adults",
            depth_thresholds=[
                DepthThreshold(name="swimming", min_depth=1.5, ing=50.0, unit="ml/h"),
                DepthThreshold(name="wading",   min_depth=0.1, ing=10.0, unit="ml/h"),
            ],
        )


def test_depth_thresholds_duplicate_names_raise():
    with pytest.raises(ValidationError, match="must be unique"):
        PopulationGroup(
            name="adults",
            depth_thresholds=[
                DepthThreshold(name="x", min_depth=0.1, ing=10.0, unit="ml/h"),
                DepthThreshold(name="x", min_depth=1.5, ing=50.0, unit="ml/h"),
            ],
        )


def test_gdp_weight_floor_out_of_range_raises():
    with pytest.raises(ValidationError):
        GDPWeight(floor=-0.1)
    with pytest.raises(ValidationError):
        GDPWeight(floor=1.5)


def test_gdp_weight_divisor_must_be_positive():
    with pytest.raises(ValidationError):
        GDPWeight(divisor=0.0)


def test_wdi_csv_sep_must_be_known():
    with pytest.raises(ValidationError):
        WDIConfig(csv_sep="|")


def test_runconfig_missing_sanitation_reduction_raises(
    default_pathogen, default_groups, default_emissions_cfg, tmp_path, write_country_toml
):
    """RunConfig must reject a country tier with no matching reduction."""
    country = CountryIndicators(
        country_code="XYZ",
        gdp_per_capita=1000.0,
        sanitation=[
            SanitationLevel(name="Safe",     urban=50.0, rural=50.0),
            SanitationLevel(name="Advanced", urban=20.0, rural=20.0),
            SanitationLevel(name="Basic",    urban=20.0, rural=20.0),
            SanitationLevel(name="None",     urban=5.0,  rural=5.0),
            SanitationLevel(name="Mystery",  urban=5.0,  rural=5.0),  # no reduction
        ],
    )
    ind = write_country_toml(tmp_path / "ind.toml", country)
    settings = SettingsConfig(
        pathogen=default_pathogen,
        population_groups=default_groups,
        emissions=default_emissions_cfg,
    )
    with pytest.raises(ValidationError, match="Mystery"):
        _run_config(ind, settings, tmp_path)


def test_runconfig_reduction_superset_is_ok(
    default_pathogen, default_groups, default_country, tmp_path, write_country_toml
):
    """Extra reductions (beyond what the country uses) are allowed."""
    emissions = EmissionsConfig(
        per_capita_ecoli_rate=1.0e9,
        total_population_group="total",
        gdp_weight=GDPWeight(),
        sanitation_reductions=[
            SanitationReduction(name=s.name, urban_reduction_factor=0.5, rural_reduction_factor=0.5)
            for s in default_country.sanitation
        ] + [
            SanitationReduction(name="Future", urban_reduction_factor=0.0, rural_reduction_factor=0.0),
        ],
    )
    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    settings = SettingsConfig(
        pathogen=default_pathogen,
        population_groups=default_groups,
        emissions=emissions,
    )
    # Should not raise — "Future" is an unused extra
    _run_config(ind, settings, tmp_path)
