"""Config loading: object defaults, relative-path resolution, country indicators."""
from __future__ import annotations

from textwrap import dedent

import pytest
from pydantic import ValidationError

from d_health.config.loaders import load_run_config


def _write(tmp_path, name: str, body: str):
    p = tmp_path / name
    p.write_text(dedent(body), encoding="utf-8")
    return p


def test_load_run_config_minimal_uses_object_defaults(tmp_path):
    indicators = _write(tmp_path, "ind.toml", """
        country_code = "SUR"
        gdp_per_capita = 7000.0
        [[sanitation]]
        name = "Safe"
        urban = 80
        rural = 50
        [[sanitation]]
        name = "Advanced"
        urban = 10
        rural = 20
        [[sanitation]]
        name = "Basic"
        urban = 5
        rural = 20
        [[sanitation]]
        name = "None"
        urban = 5
        rural = 10
    """)
    # No [settings] table at all: every field defaults to a bundled object.
    run = _write(tmp_path, "config.toml", f"""
        [exposure]
        population = "p.tif"
        urban_rural = "u.tif"
        country_indicators = "{indicators.as_posix()}"

        [event]
        flood_depth_map = "x.tif"

        [output]
        out_dir = "out"
        plots = false
    """)
    cfg = load_run_config(run)
    # Model defaults filled in from Python objects
    assert cfg.settings.pathogen.selected == "E.coli"
    assert cfg.settings.emissions.total_population_group == "total"
    assert len(cfg.settings.population_groups) == 2
    assert {g.name for g in cfg.settings.population_groups} == {"adults", "children"}
    # Country indicators are read from the referenced TOML on demand
    country = cfg.exposure.load_country_indicators()
    assert country.country_code == "SUR"
    assert len(country.sanitation) == 4


def test_load_run_config_resolves_relative_inputs_against_run_toml(tmp_path):
    # config.toml lives in a subdirectory; all input paths are relative to it.
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    _write(cfg_dir, "ind.toml", """
        country_code = "SUR"
        gdp_per_capita = 7000.0
        [[sanitation]]
        name = "Safe"
        urban = 100
        rural = 100
    """)
    run = _write(cfg_dir, "config.toml", """
        [exposure]
        population = "p.tif"
        urban_rural = "u.tif"
        country_indicators = "ind.toml"

        [event]
        flood_depth_map = "x.tif"

        [output]
        out_dir = "out"
        plots = false
    """)
    cfg = load_run_config(run)
    # Relative input paths are resolved against the config.toml's directory,
    # independent of the current working directory.
    assert cfg.event.flood_depth_map == (cfg_dir / "x.tif").resolve()
    assert cfg.exposure.population == (cfg_dir / "p.tif").resolve()
    assert cfg.exposure.urban_rural == (cfg_dir / "u.tif").resolve()
    assert cfg.exposure.country_indicators == (cfg_dir / "ind.toml").resolve()


def test_load_run_config_user_overrides_population_groups(tmp_path):
    indicators = _write(tmp_path, "ind.toml", """
        country_code = "SUR"
        gdp_per_capita = 7000.0
        [[sanitation]]
        name = "Safe"
        urban = 100
        rural = 100
    """)
    run = _write(tmp_path, "config.toml", f"""
        [exposure]
        population = "p.tif"
        urban_rural = "u.tif"
        country_indicators = "{indicators.as_posix()}"

        [event]
        flood_depth_map = "x.tif"

        [output]
        out_dir = "out"
        plots = false

        [[settings.population_groups]]
        name = "elderly"
        depth_thresholds = [
          {{ name = "wading",   min_depth = 0.1, ing = 8.0,  unit = "ml/h" }},
          {{ name = "swimming", min_depth = 1.5, ing = 40.0, unit = "ml/h" }},
        ]
    """)
    cfg = load_run_config(run)
    # User list replaces the default population_groups wholesale.
    assert [g.name for g in cfg.settings.population_groups] == ["elderly"]


def test_country_indicators_missing_field_raises(tmp_path):
    indicators = _write(tmp_path, "bad.toml", """
        country_code = "SUR"
        # missing gdp_per_capita
        [[sanitation]]
        name = "Safe"
        urban = 100
        rural = 100
    """)
    run = _write(tmp_path, "config.toml", f"""
        [exposure]
        population = "p.tif"
        urban_rural = "u.tif"
        country_indicators = "{indicators.as_posix()}"

        [event]
        flood_depth_map = "x.tif"

        [output]
        out_dir = "out"
        plots = false
    """)
    # The exposure validator parses the country TOML at load time and fails.
    with pytest.raises(ValidationError, match="gdp_per_capita"):
        load_run_config(run)
