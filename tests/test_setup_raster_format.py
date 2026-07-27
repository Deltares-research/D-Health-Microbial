"""The raster format is chosen once at setup and inherited by run configs."""

from __future__ import annotations

import tomllib

import pytest
import tomli_w

from d_health.config.setup import load_setup_config
from d_health.model.setup import (
    ModelSetupOverrides,
    model_setup,
    write_run_config_from_setup,
)


def test_setup_overrides_default_to_netcdf():
    assert ModelSetupOverrides().raster_format == "netcdf"


def test_setup_overrides_reject_unknown_format():
    with pytest.raises(ValueError):
        ModelSetupOverrides(raster_format="geopackage")


_METADATA = {
    "country_code": "SUR",
    "aoi_bounds": [-55.3, 5.7, -55.0, 5.9],
    "country_source": "manual_override",
}


def _write_settings(tmp_path, indicators_path, raster_format, suffix=".tif"):
    """A minimal settings.toml of the shape model_setup produces."""
    (tmp_path / "data").mkdir(exist_ok=True)
    payload = {
        "exposure": {
            "population": f"data/sur_population_2020_combined{suffix}",
            "urban_rural": f"data/sur_urban_rural{suffix}",
            "country_indicators": str(indicators_path).replace("\\", "/"),
        },
        "settings": {},
        "metadata": _METADATA,
    }
    if raster_format is not None:
        payload["output"] = {"raster_format": raster_format}
    path = tmp_path / "settings.toml"
    path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    return path


def test_settings_toml_output_table_validates(
    tmp_path, write_country_toml, default_country
):
    """SetupConfig is extra='forbid', so [output] needs a field to land in."""
    indicators = write_country_toml(tmp_path / "ind.toml", default_country)
    settings = _write_settings(tmp_path, indicators, "geotiff")

    cfg = load_setup_config(settings)
    assert cfg.output.raster_format == "geotiff"


def test_setup_config_output_defaults_to_netcdf(
    tmp_path, write_country_toml, default_country
):
    """A settings.toml with no [output] table at all — e.g. one written before
    the format option existed — still loads."""
    indicators = write_country_toml(tmp_path / "ind.toml", default_country)
    settings = _write_settings(tmp_path, indicators, None, suffix=".nc")

    assert load_setup_config(settings).output.raster_format == "netcdf"


def test_run_config_inherits_the_setup_format(
    tmp_path, write_country_toml, default_country
):
    indicators = write_country_toml(tmp_path / "ind.toml", default_country)
    settings = _write_settings(tmp_path, indicators, "geotiff")
    flood = tmp_path / "flood.tif"
    flood.touch()

    run_config = write_run_config_from_setup(
        settings, flood, tmp_path / "run" / "config.toml"
    )

    with run_config.open("rb") as f:
        payload = tomllib.load(f)
    assert payload["output"]["raster_format"] == "geotiff"


def _patch_preprocessing(monkeypatch):
    """Stub the three network-bound preprocessing calls model_setup makes."""

    def _fake_raster(*args, **kwargs):
        output_path = args[2] if len(args) > 2 else args[0]
        output_path.write_text("raster", encoding="utf-8")
        return output_path

    def _fake_country(country_code, output_path, **kwargs):
        output_path.write_text(
            'country_code = "SUR"\ngdp_per_capita = 7000.0\n'
            '[[sanitation]]\nname = "Safe"\nurban = 100\nrural = 100\n',
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr("d_health.model.setup.get_population_data", _fake_raster)
    monkeypatch.setattr("d_health.model.setup.get_smod_data", _fake_raster)
    monkeypatch.setattr("d_health.model.setup.get_country_indicators", _fake_country)


@pytest.mark.parametrize(("fmt", "suffix"), [("netcdf", ".nc"), ("geotiff", ".tif")])
def test_model_setup_writes_inputs_with_the_chosen_suffix(
    monkeypatch, tmp_path, fmt, suffix
):
    _patch_preprocessing(monkeypatch)

    result = model_setup(
        aoi=(-55.27, 5.78, -55.10, 5.93),
        root_dir=tmp_path / "setup",
        overrides=ModelSetupOverrides(country_code="SUR", raster_format=fmt),
    )

    assert result.population.suffix == suffix
    assert result.urban_rural.suffix == suffix

    payload = tomllib.loads(result.settings_toml.read_text(encoding="utf-8"))
    assert payload["output"]["raster_format"] == fmt
    assert payload["exposure"]["population"].endswith(suffix)
    assert payload["exposure"]["urban_rural"].endswith(suffix)
