from __future__ import annotations

import tomllib

from d_health.config.loaders import load_run_config
from d_health.config.setup import load_setup_config
from d_health.model.setup import (
    ModelSetupOverrides,
    derive_country_from_aoi,
    model_setup,
    write_run_config_from_setup,
)


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_derive_country_from_aoi_uses_reverse_geocode_and_iso_mapping(monkeypatch):
    calls: list[str] = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        if "nominatim.openstreetmap.org" in url:
            return _DummyResponse(
                {
                    "address": {
                        "country_code": "sr",
                        "country": "Suriname",
                    }
                }
            )
        if "api.worldbank.org" in url:
            return _DummyResponse([{}, [{"id": "SUR"}]])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("d_health.model.setup.requests.get", _fake_get)

    iso3, country_name, bounds = derive_country_from_aoi((-55.27, 5.78, -55.10, 5.93))

    assert iso3 == "SUR"
    assert country_name == "Suriname"
    assert bounds == (-55.27, 5.78, -55.10, 5.93)
    assert len(calls) == 2


def test_model_setup_writes_settings_without_event_and_supports_manual_iso(
    monkeypatch, tmp_path
):
    def _fake_population(country, year, output_path, **kwargs):
        output_path.write_text("population", encoding="utf-8")
        return output_path

    def _fake_smod(output_path, **kwargs):
        output_path.write_text("urban_rural", encoding="utf-8")
        return output_path

    def _fake_country(country_code, output_path, **kwargs):
        output_path.write_text(
            "\n".join(
                [
                    'country_code = "SUR"',
                    "gdp_per_capita = 7000.0",
                    "[[sanitation]]",
                    'name = "Safe"',
                    "urban = 100",
                    "rural = 100",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr("d_health.model.setup.get_population_data", _fake_population)
    monkeypatch.setattr("d_health.model.setup.get_smod_data", _fake_smod)
    monkeypatch.setattr("d_health.model.setup.get_country_indicators", _fake_country)

    def _should_not_call(*args, **kwargs):
        raise AssertionError(
            "derive_country_from_aoi should not be called with manual override"
        )

    monkeypatch.setattr(
        "d_health.model.setup.derive_country_from_aoi", _should_not_call
    )

    setup_root = tmp_path / "setup"
    result = model_setup(
        aoi=(-55.27, 5.78, -55.10, 5.93),
        root_dir=setup_root,
        overrides=ModelSetupOverrides(country_code="SUR"),
    )

    assert result.country_code == "SUR"
    assert result.settings_toml.exists()

    payload = tomllib.loads(result.settings_toml.read_text(encoding="utf-8"))
    assert "event" not in payload
    assert "output" not in payload
    assert payload["exposure"]["population"] == "data/sur_population_2020_combined.nc"
    assert payload["exposure"]["urban_rural"] == "data/sur_urban_rural.nc"
    assert payload["exposure"]["country_indicators"] == "data/sur_indicators.toml"
    assert payload["metadata"]["country_code"] == "SUR"
    assert payload["metadata"]["country_source"] == "manual_override"

    cfg = load_setup_config(result.settings_toml)
    assert (
        cfg.exposure.population
        == (setup_root / "data" / "sur_population_2020_combined.nc").resolve()
    )
    assert not (setup_root / "outputs" / "run").exists()


def test_write_run_config_from_setup(tmp_path):
    setup_dir = tmp_path / "setup"
    setup_dir.mkdir(parents=True)
    settings_toml = setup_dir / "settings.toml"
    settings_toml.write_text(
        "\n".join(
            [
                "[exposure]",
                'population = "data/sur_population_2020_combined.nc"',
                'urban_rural = "data/sur_urban_rural.nc"',
                'country_indicators = "data/sur_indicators.toml"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    run_toml = tmp_path / "run" / "config.toml"
    out = write_run_config_from_setup(
        settings_toml,
        flood_depth_map="data/flood_extremes/flood_wl3m_paramaribo.tif",
        run_config_path=run_toml,
        output_out_dir="outputs/run/scenario_wl3m",
    )

    assert out == run_toml
    payload = tomllib.loads(run_toml.read_text(encoding="utf-8"))
    assert payload["event"]["flood_depth_map"].endswith("flood_wl3m_paramaribo.tif")
    assert payload["exposure"]["population"].endswith("sur_population_2020_combined.nc")
    assert payload["output"]["out_dir"].endswith("scenario_wl3m")
    assert payload["output"]["plots"] is True


def test_write_run_config_from_setup_nested_run_dir_resolves_exposure_paths(tmp_path):
    setup_dir = tmp_path / "data" / "setup_paramaribo"
    setup_data = setup_dir / "data"
    setup_data.mkdir(parents=True)
    indicators = setup_data / "sur_indicators.toml"
    indicators.write_text(
        "\n".join(
            [
                'country_code = "SUR"',
                "gdp_per_capita = 7000.0",
                "[[sanitation]]",
                'name = "Safe"',
                "urban = 100",
                "rural = 100",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    settings_toml = setup_dir / "settings.toml"
    settings_toml.write_text(
        "\n".join(
            [
                "[exposure]",
                'population = "data/sur_population_2020_combined.nc"',
                'urban_rural = "data/sur_urban_rural.nc"',
                'country_indicators = "data/sur_indicators.toml"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    flood_map = tmp_path / "data" / "flood_extremes" / "flood_wl1m_paramaribo.tif"
    flood_map.parent.mkdir(parents=True)
    flood_map.write_text("dummy", encoding="utf-8")

    scenario_dir = tmp_path / "outputs" / "run" / "scenario_wl1m"
    run_toml = scenario_dir / "config.toml"
    write_run_config_from_setup(
        settings_toml=settings_toml,
        flood_depth_map=flood_map,
        run_config_path=run_toml,
        output_out_dir=scenario_dir,
    )

    cfg = load_run_config(run_toml)
    assert cfg.exposure.country_indicators == indicators.resolve()
    assert cfg.event.flood_depth_map == flood_map.resolve()
    assert cfg.output.out_dir == scenario_dir.resolve()
