"""The --format flag reaches the config on both subcommands."""

from __future__ import annotations

import pytest

from d_health.cli import _apply_overrides, _build_parser
from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
)


def _minimal_config(tmp_path, write_country_toml, default_country, raster_format):
    """A RunConfig built on model defaults — enough to exercise _apply_overrides."""
    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    return RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "pop.tif",
            urban_rural=tmp_path / "ur.tif",
            country_indicators=ind,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "flood.tif"),
        output=OutputConfig(
            out_dir=tmp_path / "out", plots=False, raster_format=raster_format
        ),
    )


def test_setup_format_defaults_to_netcdf():
    args = _build_parser().parse_args(["setup", "--bbox", "0", "0", "1", "1"])
    assert args.format == "netcdf"


def test_setup_accepts_geotiff():
    args = _build_parser().parse_args(
        ["setup", "--bbox", "0", "0", "1", "1", "--format", "geotiff"]
    )
    assert args.format == "geotiff"


def test_setup_rejects_unknown_format():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["setup", "--bbox", "0", "0", "1", "1", "--format", "geopackage"]
        )


def test_run_format_defaults_to_none_so_the_config_wins():
    args = _build_parser().parse_args(["run"])
    assert args.format is None


def test_run_format_override_replaces_the_config_value(
    tmp_path, write_country_toml, default_country
):
    config = _minimal_config(tmp_path, write_country_toml, default_country, "netcdf")

    updated = _apply_overrides(config, None, False, "geotiff")

    assert updated.output.raster_format == "geotiff"
    assert config.output.raster_format == "netcdf"  # frozen: original untouched


def test_run_without_format_leaves_the_config_alone(
    tmp_path, write_country_toml, default_country
):
    config = _minimal_config(tmp_path, write_country_toml, default_country, "geotiff")

    updated = _apply_overrides(config, None, False, None)

    assert updated.output.raster_format == "geotiff"
