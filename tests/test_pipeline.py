"""Test #8: end-to-end run_model with synthetic inputs."""

from __future__ import annotations

import numpy as np

from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
    SettingsConfig,
)
from d_health.model.inputs import ModelInputs
from d_health.model.pipeline import run_model


def _build_config(
    default_pathogen,
    default_groups,
    default_emissions_cfg,
    default_country,
    tmp_path,
    write_country_toml,
    *,
    plots: bool = False,
):
    # Country indicators are read from disk at run time, so materialise them.
    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    return RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "pop.tif",
            urban_rural=tmp_path / "ur.tif",
            country_indicators=ind,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "flood.tif"),
        output=OutputConfig(out_dir=tmp_path / "out", plots=plots),
        settings=SettingsConfig(
            pathogen=default_pathogen,
            population_groups=default_groups,
            emissions=default_emissions_cfg,
        ),
    )


def test_run_model_shape_parity_and_totals(
    tmp_path,
    small_meta,
    flood_16x16,
    population_16x16,
    urban_rural_16x16,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
    default_country,
    write_country_toml,
):
    config = _build_config(
        default_pathogen,
        default_groups,
        default_emissions_cfg,
        default_country,
        tmp_path,
        write_country_toml,
    )
    inputs = ModelInputs(
        flood=flood_16x16,
        flood_meta=small_meta,
        population=population_16x16,
        urban_rural=urban_rural_16x16,
    )

    outputs = run_model(config, inputs=inputs)

    # Shape parity
    assert outputs.emissions.shape == flood_16x16.shape
    assert outputs.pathogen_conc.shape == flood_16x16.shape
    for name in ("adults", "children"):
        assert outputs.doses[name].shape == flood_16x16.shape
        assert outputs.risks[name].shape == flood_16x16.shape
        assert outputs.infected[name].shape == flood_16x16.shape

    # Totals keys & non-negativity
    assert set(outputs.totals) == {"infected_adults", "infected_children"}
    for k, v in outputs.totals.items():
        assert v >= 0, f"{k} should be non-negative, got {v}"

    # Emissions is non-negative everywhere
    assert np.all(outputs.emissions >= 0)

    # Risks are bounded
    for name in ("adults", "children"):
        risk = outputs.risks[name]
        finite = risk[~np.isnan(risk)]
        assert np.all(finite >= 0)
        assert np.all(finite < 1)

    # Output rasters exist (per-group quantities are stacked into one netCDF
    # each, along the group dim).
    for label in (
        "emissions",
        "pathogen_conc",
        "flood_classes",
        "dose",
        "risk",
        "infected",
    ):
        assert label in outputs.paths, f"missing output path for {label}"
        assert outputs.paths[label].exists()
        assert outputs.paths[label].suffix == ".nc"


def test_run_model_writes_pathogen_conc_plot_when_plots_enabled(
    tmp_path,
    small_meta,
    flood_16x16,
    population_16x16,
    urban_rural_16x16,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
    default_country,
    write_country_toml,
):
    config = _build_config(
        default_pathogen,
        default_groups,
        default_emissions_cfg,
        default_country,
        tmp_path,
        write_country_toml,
        plots=True,
    )
    inputs = ModelInputs(
        flood=flood_16x16,
        flood_meta=small_meta,
        population=population_16x16,
        urban_rural=urban_rural_16x16,
    )

    outputs = run_model(config, inputs=inputs)

    png = outputs.paths["pathogen_conc"].with_suffix(".png")
    assert png.exists()
    assert png.stat().st_size > 0
