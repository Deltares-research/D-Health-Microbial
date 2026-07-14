"""Regression: load_inputs must return arrays that actually share a grid.

``align_rasters`` clips *both* of its returned arrays to the input's footprint.
``load_inputs`` calls it twice, and used to discard the clipped target of the
second call (``urban_rural_da, _ = ...``). So whenever the urban/rural raster
covered less ground than the flood map, the returned ``urban_rural`` sat on a
smaller grid than ``flood`` and ``population`` — and nothing checked.

The mismatch then surfaced several frames away as
``IndexError: boolean index did not match indexed array along axis 0`` from
inside ``compute_emissions``, a function with no idea it had been handed
inconsistent inputs. GHS-SMOD is global, so this stayed hidden; it would fire the
moment someone supplied a locally-clipped urban/rural raster.
"""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import from_origin

from d_health.config.run import EventConfig, ExposureConfig
from d_health.io import from_numpy, write_netcdf
from d_health.model.inputs import load_inputs


def _indicators(tmp_path):
    ind = tmp_path / "ind.toml"
    ind.write_text(
        'country_code = "SUR"\n'
        "gdp_per_capita = 7000.0\n"
        "[[sanitation]]\n"
        'name = "None"\n'
        "urban = 100\n"
        "rural = 100\n",
        encoding="utf-8",
    )
    return ind


def _write(tmp_path, flood, pop, ur):
    """Write the three rasters; each may sit on its own grid."""
    t = from_origin(0.0, 1.0, 0.01, 0.01)
    crs = "EPSG:4326"
    flood_p = write_netcdf(from_numpy(flood, t, crs, name="flood"), tmp_path / "f.nc")
    pop_p = write_netcdf(
        from_numpy(
            pop, t, crs, name="population", group=("children", "adults", "total")
        ),
        tmp_path / "p.nc",
    )
    ur_p = write_netcdf(
        from_numpy(ur, t, crs, name="urban_rural", nodata=0), tmp_path / "u.nc"
    )
    exposure = ExposureConfig(
        population=pop_p, urban_rural=ur_p, country_indicators=_indicators(tmp_path)
    )
    return exposure, EventConfig(flood_depth_map=flood_p)


def _population(shape):
    children = np.full(shape, 10.0, dtype=np.float32)
    adults = np.full(shape, 30.0, dtype=np.float32)
    return np.stack([children, adults, children + adults])


def test_smaller_urban_rural_footprint_still_yields_a_common_grid(tmp_path):
    """urban_rural covering less ground than the flood map must not desync the grid.

    Before the fix this returned flood (10, 10) against urban_rural (6, 5).
    """
    flood = np.full((10, 10), 1.0, dtype=np.float32)
    ur = np.ones((5, 5), dtype=np.uint8)  # deliberately smaller footprint

    inputs = load_inputs(*_write(tmp_path, flood, _population((10, 10)), ur))

    assert inputs.flood.shape == inputs.urban_rural.shape
    assert inputs.flood.shape == inputs.population.shape[1:]

    # And the common grid is the *intersection*, not one raster's grid imposed
    # on the others — so it shrank to urban_rural's footprint.
    assert inputs.flood.shape < (10, 10)


def test_full_overlap_is_unchanged(tmp_path):
    """The common case (urban_rural covers everything) keeps the full grid."""
    flood = np.full((10, 10), 1.0, dtype=np.float32)
    ur = np.ones((10, 10), dtype=np.uint8)

    inputs = load_inputs(*_write(tmp_path, flood, _population((10, 10)), ur))

    assert inputs.flood.shape == (10, 10)
    assert inputs.urban_rural.shape == (10, 10)
    assert inputs.population.shape == (3, 10, 10)


def test_population_counts_are_selected_not_resampled(tmp_path):
    """Re-clipping population must not resample it — headcounts are extensive.

    Resampling a count raster invents or destroys people. The clip must select
    whole cells, leaving their values untouched.
    """
    flood = np.full((10, 10), 1.0, dtype=np.float32)
    ur = np.ones((5, 5), dtype=np.uint8)

    inputs = load_inputs(*_write(tmp_path, flood, _population((10, 10)), ur))

    # Every surviving cell still carries its original, unaveraged headcount.
    assert np.allclose(inputs.population.sel(group="children").values, 10.0)
    assert np.allclose(inputs.population.sel(group="adults").values, 30.0)
    assert np.allclose(inputs.population.sel(group="total").values, 40.0)


def test_negative_flood_depths_are_clipped_to_dry(tmp_path, caplog):
    """A DEM-differenced flood map carries negatives on high ground.

    Left alone they produce a negative concentration, a negative dose and a
    *negative risk*, which np.nansum then quietly subtracts from the totals.
    """
    flood = np.full((10, 10), 1.0, dtype=np.float32)
    flood[:5, :] = -2.5  # dry high ground, encoded as negative depth
    ur = np.ones((10, 10), dtype=np.uint8)

    with caplog.at_level("WARNING"):
        inputs = load_inputs(*_write(tmp_path, flood, _population((10, 10)), ur))

    assert not (inputs.flood < 0).any(), "negative depths must be clipped to 0"
    assert (inputs.flood[:5, :] == 0.0).all(), "negatives become dry, not flooded"
    assert (inputs.flood[5:, :] == 1.0).all(), "real depths are left alone"
    assert "negative-depth" in caplog.text, "the clipping must not be silent"


def test_disjoint_rasters_raise_a_readable_error(tmp_path):
    """Non-overlapping footprints fail loudly, naming the problem."""
    flood = np.full((10, 10), 1.0, dtype=np.float32)
    ur = np.ones((10, 10), dtype=np.uint8)

    exposure, event = _write(tmp_path, flood, _population((10, 10)), ur)
    # Move urban_rural far away so it cannot intersect the flood map.
    far = write_netcdf(
        from_numpy(
            ur, from_origin(50.0, 50.0, 0.01, 0.01), "EPSG:4326", name="urban_rural"
        ),
        tmp_path / "far.nc",
    )
    exposure = ExposureConfig(
        population=exposure.population,
        urban_rural=far,
        country_indicators=exposure.country_indicators,
    )

    with pytest.raises(ValueError, match="do not overlap|common grid"):
        load_inputs(exposure, event)
