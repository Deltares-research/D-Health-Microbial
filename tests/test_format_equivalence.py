"""The output format must not change the science.

Every other format test asserts on *metadata* — suffix, CRS, band names — or
passes ``inputs=`` and skips the read-back entirely:

* ``test_pipeline_output_format.py`` checks suffixes and CRS, but calls
  ``run_model(config, inputs=...)``, so ``load_inputs`` never runs.
* ``test_georeferencing.py`` checks files written directly by ``write_raster``.
* ``test_setup_raster_format.py`` / ``test_cli_format.py`` check that the format
  *propagates* through setup → settings.toml → run config → CLI.

None of them asks the question a format option actually raises: does reading a
``.tif`` back give the same numbers as reading a ``.nc``?

The two formats do not round-trip identically. GeoTIFF carries a nodata value,
so ``get_smod_data`` writes unclassified urban/rural as ``nodata=0``, and
``load_raster(masked=True)`` hands it back as ``NaN`` in a float array. netCDF
keeps a literal ``0`` in an integer array. ``load_inputs`` reconciles the two
with ``np.where(np.isnan(...), 0, ...)``.

Note what that coercion does and does not buy, because it is easy to overclaim
(measured by deleting it and re-running these tests):

* It does **not** change the numbers. ``compute_emissions`` routes both ``NaN``
  and ``0`` into the same ``nodata_mask = ~(urban_mask | rural_mask)`` branch,
  so emissions, risk and totals are identical either way.
* It **does** hold the contract ``ModelInputs`` documents — ``urban_rural`` is
  an integer array where ``1=urban, 2=rural, 0=nodata`` — and it keeps the code
  off a ``float→int8`` cast of ``NaN``, which numpy flags as
  ``invalid value encountered in cast`` and whose result is not defined by the
  standard (it merely happens to be ``0`` on x86).

So these tests are not guarding a knife-edge in the sanitation branch. They are
guarding the whole read-back path — band-to-group mapping and ordering, group
labels, grid alignment, CRS, flood values — which is where a GeoTIFF regression
would actually surface, and which nothing else exercises end to end.
"""

from __future__ import annotations

import numpy as np
import pytest

from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
    SettingsConfig,
)
from d_health.io import from_numpy, raster_path, write_raster
from d_health.model.inputs import load_inputs
from d_health.model.pipeline import run_model

# What preprocessing.smod.get_smod_data writes for "neither urban nor rural".
SMOD_NODATA = 0


def _write_inputs(in_dir, fmt, small_meta, flood, population, urban_rural):
    """Write the three model inputs to disk in ``fmt``; return their paths."""
    in_dir.mkdir(parents=True, exist_ok=True)
    transform, crs = small_meta["transform"], small_meta["crs"]

    flood_path = raster_path(in_dir, "flood", fmt)
    write_raster(
        from_numpy(flood, transform, crs, name="flood"),
        flood_path,
        descriptions=("flood_depth_m",),
    )

    pop_path = raster_path(in_dir, "population", fmt)
    write_raster(
        population,  # already a DataArray with a labelled group dim
        pop_path,
        descriptions=("children_0_9", "adults_10_plus", "total"),
        units="people",
    )

    ur_path = raster_path(in_dir, "urban_rural", fmt)
    write_raster(
        from_numpy(urban_rural, transform, crs, name="urban_rural"),
        ur_path,
        descriptions=("urban_rural",),
        # Mirrors get_smod_data: 0 means unclassified, and in GeoTIFF that is
        # written as the nodata value. This is the round-trip under test.
        nodata=SMOD_NODATA if fmt == "geotiff" else None,
    )
    return flood_path, pop_path, ur_path


def _build_config(tmp_path, fmt, paths, indicators):
    flood_path, pop_path, ur_path = paths
    return dict(
        exposure=ExposureConfig(
            population=pop_path,
            urban_rural=ur_path,
            country_indicators=indicators,
        ),
        event=EventConfig(flood_depth_map=flood_path),
        output=OutputConfig(
            out_dir=tmp_path / fmt / "out", plots=False, raster_format=fmt
        ),
    )


@pytest.fixture
def run_in_format(
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
):
    """Run the full pipeline from rasters on disk in the requested format.

    Deliberately does *not* pass ``inputs=`` — going through ``load_inputs`` is
    the entire point of these tests.
    """

    def _run(fmt, urban_rural=None):
        paths = _write_inputs(
            tmp_path / fmt / "in",
            fmt,
            small_meta,
            flood_16x16,
            population_16x16,
            urban_rural_16x16 if urban_rural is None else urban_rural,
        )
        indicators = write_country_toml(tmp_path / f"{fmt}_ind.toml", default_country)
        config = RunConfig(
            **_build_config(tmp_path, fmt, paths, indicators),
            settings=SettingsConfig(
                pathogen=default_pathogen,
                population_groups=default_groups,
                emissions=default_emissions_cfg,
            ),
        )
        return run_model(config)

    return _run


def test_totals_agree_across_formats(run_in_format):
    """Same inputs, two on-disk formats, same headline numbers."""
    nc = run_in_format("netcdf")
    tif = run_in_format("geotiff")

    assert set(nc.totals) == set(tif.totals)
    for key, value in nc.totals.items():
        assert value == pytest.approx(
            tif.totals[key], rel=1e-9
        ), f"{key} differs: netcdf={value} geotiff={tif.totals[key]}"


def test_emissions_agree_cell_by_cell_across_formats(run_in_format):
    """Totals can agree while cells diverge and cancel out.

    Emissions is the layer ``urban_rural`` feeds directly, so a nodata
    round-trip difference shows up here first and most clearly.
    """
    nc = run_in_format("netcdf")
    tif = run_in_format("geotiff")
    np.testing.assert_allclose(nc.emissions, tif.emissions, rtol=1e-9)


def test_risk_agrees_cell_by_cell_across_formats(run_in_format):
    """The end of the chain, NaNs included — dry cells must stay NaN in both."""
    nc = run_in_format("netcdf")
    tif = run_in_format("geotiff")
    for group in nc.risks:
        np.testing.assert_allclose(
            nc.risks[group], tif.risks[group], rtol=1e-9, equal_nan=True
        )


def test_unclassified_cells_survive_the_geotiff_nodata_roundtrip(
    tmp_path,
    small_meta,
    flood_16x16,
    population_16x16,
    write_country_toml,
    default_country,
):
    """GeoTIFF writes unclassified as nodata=0; load_raster returns it as NaN.

    ``load_inputs`` must turn it back into ``0`` so ``ModelInputs.urban_rural``
    holds the integer codes its docstring promises. Deleting that coercion does
    not move the totals — see this module's docstring — but it does put NaN in
    an array documented as ``1=urban, 2=rural, 0=nodata`` and leaves the class
    codes to an undefined float→int cast. This is the test that fails if it
    goes.
    """
    urban_rural = np.zeros((16, 16), dtype=np.int16)
    urban_rural[:8] = 1  # urban
    urban_rural[8:12] = 2  # rural
    # rows 12-15 stay 0 = unclassified

    paths = _write_inputs(
        tmp_path / "in",
        "geotiff",
        small_meta,
        flood_16x16,
        population_16x16,
        urban_rural,
    )
    flood_path, pop_path, ur_path = paths
    inputs = load_inputs(
        ExposureConfig(
            population=pop_path,
            urban_rural=ur_path,
            country_indicators=write_country_toml(
                tmp_path / "ind.toml", default_country
            ),
        ),
        EventConfig(flood_depth_map=flood_path),
    )

    assert not np.isnan(inputs.urban_rural).any(), "nodata leaked through as NaN"
    assert (inputs.urban_rural[12:] == 0).all(), "unclassified cells were not preserved"
    assert (inputs.urban_rural[:8] == 1).all(), "urban cells were not preserved"
    assert (inputs.urban_rural[8:12] == 2).all(), "rural cells were not preserved"
