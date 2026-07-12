"""Pin the public API, so docs/API_REFERENCE.md cannot silently rot into fiction.

The previous API reference documented an API that did not exist: `align_rasters`
with `rasters=`/`reference=`/`output_dir=` parameters (none real), a
`WDIConfig(country_code=...)` field that was never defined, a `build_from_wdi`
signature with the arguments in the wrong shape, and `ModelInputs.population`
typed as a numpy array when it is an xarray DataArray. Every example in it would
have raised.

Prose drifts silently; a test does not. These assertions are the contract the
reference documents — if you change a public signature, this fails, and the doc
gets updated in the same commit.
"""

from __future__ import annotations

import inspect

import numpy as np
import xarray as xr

import d_health
from d_health.config.emissions import EmissionsConfig
from d_health.config.preprocessing import WDIConfig, WorldPopConfig
from d_health.model.inputs import ModelInputs
from d_health.model.setup import ModelSetupResult
from d_health.postprocessing import DEFAULT_RISK_EDGES

EXPECTED_EXPORTS = {
    "WorldPopConfig",
    "get_population_data",
    "GHSSmodConfig",
    "get_smod_data",
    "WDIConfig",
    "get_world_bank_data",
    "align_rasters",
    "build_from_wdi",
    "get_country_indicators",
    "RunConfig",
    "ModelOutputs",
    "ModelSetupOverrides",
    "ModelSetupResult",
    "load_run_config",
    "derive_country_from_aoi",
    "model_setup",
    "write_run_config_from_setup",
    "run_model",
    "run_model_from_toml",
    "__version__",
}


def test_public_exports_are_stable():
    """`from d_health import ...` keeps working for everything documented."""
    assert set(d_health.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(d_health, name), f"{name} is in __all__ but not importable"


def _params(func) -> list[str]:
    return list(inspect.signature(func).parameters)


def test_documented_signatures():
    """The exact parameter names the API reference shows."""
    assert _params(d_health.align_rasters) == ["input_da", "target_da", "resampling"]
    assert _params(d_health.model_setup) == ["aoi", "root_dir", "overrides"]
    assert _params(d_health.write_run_config_from_setup) == [
        "settings_toml",
        "flood_depth_map",
        "run_config_path",
        "output_out_dir",
    ]
    assert _params(d_health.build_from_wdi) == [
        "wdi_csv",
        "country_code",
        "out_path",
        "sep",
    ]
    assert _params(d_health.get_country_indicators) == [
        "country_code",
        "output_path",
        "cfg",
    ]
    assert _params(d_health.get_population_data) == [
        "country",
        "year",
        "output_path",
        "clip",
        "cfg",
        "child_ages",
        "adult_ages",
    ]
    # No country argument: SMOD is a global product, clipped by geometry.
    assert _params(d_health.get_smod_data) == ["output_path", "clip", "cfg"]
    assert _params(d_health.run_model) == ["config", "inputs"]
    assert _params(d_health.run_model_from_toml) == ["path"]
    assert _params(d_health.load_run_config) == ["path"]


def test_align_rasters_returns_two_arrays():
    """It returns (aligned_input, clipped_target) — not a single array, and it
    does not write files."""
    ret = inspect.signature(d_health.align_rasters).return_annotation
    assert "tuple" in str(ret)


def test_model_setup_result_fields():
    """The field names the docs print — `root_dir`, not `setup_root`."""
    assert set(ModelSetupResult.model_fields) == {
        "root_dir",
        "settings_toml",
        "population",
        "urban_rural",
        "country_indicators",
        "country_code",
        "country_name",
    }


def test_model_inputs_population_is_an_xarray_not_a_numpy_array():
    """Documented as xr.DataArray, because you select layers by group name."""
    hints = ModelInputs.__annotations__
    assert "DataArray" in hints["population"]
    assert "ndarray" in hints["flood"]
    assert "ndarray" in hints["urban_rural"]


def test_wdi_config_has_no_country_code_field():
    """The country is an argument, not config — the old docs got this wrong."""
    assert "country_code" not in WDIConfig.model_fields
    assert set(WDIConfig.model_fields) == {"indicator_codes", "csv_sep"}


def test_documented_defaults():
    assert DEFAULT_RISK_EDGES == (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    assert EmissionsConfig().nodata_sanitation == "none"
    assert EmissionsConfig().per_capita_ecoli_rate == 1.0e9
    assert WorldPopConfig().layout == "global1_2000_2020"
    assert WorldPopConfig().resolution == "100m"


def test_pathogen_defaults_are_the_documented_teunis_values():
    from d_health.config.pathogen import PathogenConfig

    active = PathogenConfig().active
    assert (active.alpha, active.beta) == (0.373, 39.71)


def test_unexposed_cells_are_nan_not_zero(
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
    """The docs tell users to aggregate with np.nansum. Hold that true."""
    from d_health.config.run import (
        EventConfig,
        ExposureConfig,
        OutputConfig,
        RunConfig,
        SettingsConfig,
    )
    from d_health.model.pipeline import run_model

    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    config = RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "p.nc",
            urban_rural=tmp_path / "u.nc",
            country_indicators=ind,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "f.nc"),
        output=OutputConfig(out_dir=tmp_path / "out", plots=False),
        settings=SettingsConfig(
            pathogen=default_pathogen,
            population_groups=default_groups,
            emissions=default_emissions_cfg,
        ),
    )
    outputs = run_model(
        config,
        inputs=ModelInputs(
            flood=flood_16x16,
            flood_meta=small_meta,
            population=population_16x16,
            urban_rural=urban_rural_16x16,
        ),
    )

    assert isinstance(outputs.emissions, np.ndarray)
    assert isinstance(population_16x16, xr.DataArray)
    # Dry cells are NaN in every downstream field, never 0.0.
    for field in (outputs.pathogen_conc, *outputs.risks.values()):
        assert np.isnan(field).any(), "dry cells must be NaN, not zero"
