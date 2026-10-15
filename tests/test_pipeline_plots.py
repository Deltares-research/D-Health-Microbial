"""`output.plots = true` writes every map, and a flood with no wet cells cannot fail it.

Every other pipeline test runs with ``plots=False``, so without this file the whole
plotting branch of ``run_model`` is unexercised.
"""

from __future__ import annotations

import matplotlib
import numpy as np
import pytest

from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
    SettingsConfig,
)
from d_health.model.inputs import ModelInputs
from d_health.model.pipeline import run_model

matplotlib.use("Agg")


@pytest.fixture
def plot_config(
    tmp_path,
    write_country_toml,
    default_country,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
):
    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    return RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "pop.tif",
            urban_rural=tmp_path / "ur.tif",
            country_indicators=ind,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "flood.tif"),
        output=OutputConfig(out_dir=tmp_path / "out", plots=True),
        settings=SettingsConfig(
            pathogen=default_pathogen,
            population_groups=default_groups,
            emissions=default_emissions_cfg,
        ),
    )


@pytest.mark.parametrize("dry", [False, True], ids=["flooded", "all_dry"])
def test_plots_written(
    plot_config,
    small_meta,
    flood_16x16,
    population_16x16,
    urban_rural_16x16,
    default_groups,
    dry,
):
    # All-dry makes pathogen_conc (and every dose/risk/infected map) all-NaN.
    flood = np.zeros_like(flood_16x16) if dry else flood_16x16
    inputs = ModelInputs(
        flood=flood,
        flood_meta=small_meta,
        population=population_16x16,
        urban_rural=urban_rural_16x16,
    )

    outputs = run_model(plot_config, inputs=inputs)

    out_dir = plot_config.output.out_dir
    if not dry:
        assert np.isfinite(outputs.pathogen_conc).any()
    expected = ["emissions.png", "pathogen_conc.png"] + [
        f"{label}_{g.name}.png"
        for label in ("dose", "risk", "infected")
        for g in default_groups
    ]
    for name in expected:
        assert (out_dir / name).is_file(), f"{name} not written"
