"""The pipeline writes its rasters in the format the config asks for."""

from __future__ import annotations

import pytest
import rasterio

from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
    SettingsConfig,
)
from d_health.model.inputs import ModelInputs
from d_health.model.pipeline import run_model

RASTER_OUTPUTS = (
    "emissions",
    "pathogen_conc",
    "flood_classes",
    "dose",
    "risk",
    "infected",
)


def _build_config(
    tmp_path,
    write_country_toml,
    default_country,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
    **output_kwargs,
):
    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    return RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "pop.tif",
            urban_rural=tmp_path / "ur.tif",
            country_indicators=ind,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "flood.tif"),
        output=OutputConfig(out_dir=tmp_path / "out", plots=False, **output_kwargs),
        settings=SettingsConfig(
            pathogen=default_pathogen,
            population_groups=default_groups,
            emissions=default_emissions_cfg,
        ),
    )


@pytest.mark.parametrize(("fmt", "suffix"), [("netcdf", ".nc"), ("geotiff", ".tif")])
def test_outputs_written_in_configured_format(
    tmp_path,
    small_meta,
    flood_16x16,
    population_16x16,
    urban_rural_16x16,
    write_country_toml,
    default_country,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
    fmt,
    suffix,
):
    config = _build_config(
        tmp_path,
        write_country_toml,
        default_country,
        default_pathogen,
        default_groups,
        default_emissions_cfg,
        raster_format=fmt,
    )
    inputs = ModelInputs(
        flood=flood_16x16,
        flood_meta=small_meta,
        population=population_16x16,
        urban_rural=urban_rural_16x16,
    )

    outputs = run_model(config, inputs=inputs)

    for key in RASTER_OUTPUTS:
        path = outputs.paths[key]
        assert path.suffix == suffix, f"{key} written as {path.suffix}"
        assert path.exists()
        with rasterio.open(path) as src:
            assert src.crs == small_meta["crs"], f"{key} lost its CRS"


def test_default_format_is_netcdf(
    tmp_path,
    write_country_toml,
    default_country,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
):
    config = _build_config(
        tmp_path,
        write_country_toml,
        default_country,
        default_pathogen,
        default_groups,
        default_emissions_cfg,
    )
    assert config.output.raster_format == "netcdf"
