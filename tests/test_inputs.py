"""load_inputs: positive flood depth preserved; population carries a group dim.

Exercises both netCDF inputs (the new default) and multi-band GeoTIFF inputs
(back-compat).
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from d_health.config.run import EventConfig, ExposureConfig
from d_health.io import from_numpy, write_netcdf
from d_health.model.inputs import load_inputs


def _build_arrays(small_meta):
    transform = small_meta["transform"]
    crs = small_meta["crs"]
    flood = np.zeros((16, 16), dtype=np.float32)
    flood[8:, :] = 2.0  # bottom half flooded at 2 m, top half dry (0)
    children = np.full((16, 16), 10.0, dtype=np.float32)
    adults = np.full((16, 16), 30.0, dtype=np.float32)
    pop = np.stack([children, adults, children + adults], axis=0)
    ur = np.ones((16, 16), dtype=np.uint8)  # all urban (1)

    flood_da = from_numpy(flood, transform, crs, name="flood")
    pop_da = from_numpy(
        pop, transform, crs, name="population", group=("children", "adults", "total")
    )
    ur_da = from_numpy(ur, transform, crs, name="urban_rural", nodata=0)
    return flood_da, pop_da, ur_da


def _configs(tmp_path, flood_p, pop_p, ur_p):
    # ExposureConfig validates the country_indicators TOML at construction, so
    # write a minimal valid one.
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
    exposure = ExposureConfig(
        population=pop_p,
        urban_rural=ur_p,
        country_indicators=ind,
    )
    event = EventConfig(flood_depth_map=flood_p)
    return exposure, event


def test_load_inputs_netcdf_keeps_positive_depth_and_group_dim(tmp_path, small_meta):
    flood_da, pop_da, ur_da = _build_arrays(small_meta)
    flood_p = write_netcdf(flood_da, tmp_path / "flood.nc")
    pop_p = write_netcdf(
        pop_da,
        tmp_path / "pop.nc",
        descriptions=("children_0_9", "adults_10_plus", "total"),
    )
    ur_p = write_netcdf(ur_da, tmp_path / "ur.nc")

    inputs = load_inputs(*_configs(tmp_path, flood_p, pop_p, ur_p))

    finite = inputs.flood[~np.isnan(inputs.flood)]
    assert np.all(finite >= 0), "depths must stay non-negative (positive = flooded)"
    assert np.any(finite > 0), "flooded cells should remain > 0"

    # population is a DataArray with a labelled group dim, selectable by name.
    assert isinstance(inputs.population, xr.DataArray)
    assert "group" in inputs.population.dims
    assert set(map(str, inputs.population["group"].values)) == {
        "children",
        "adults",
        "total",
    }
    assert np.allclose(
        inputs.population.sel(group="total").values, 40.0, equal_nan=True
    )


def test_load_inputs_reads_geotiff_backcompat(tmp_path, small_meta):
    """A multi-band GeoTIFF population still loads (band → group)."""
    flood_da, pop_da, ur_da = _build_arrays(small_meta)
    flood_p = tmp_path / "flood.tif"
    flood_da.rio.to_raster(flood_p)
    pop_p = tmp_path / "pop.tif"
    # rasterio bands are positional integers; group → band for the GeoTIFF.
    pop_da.rename({"group": "band"}).assign_coords(band=[1, 2, 3]).rio.to_raster(pop_p)
    ur_p = tmp_path / "ur.tif"
    ur_da.rio.to_raster(ur_p)

    inputs = load_inputs(*_configs(tmp_path, flood_p, pop_p, ur_p))

    assert inputs.flood.shape == (16, 16)
    assert "group" in inputs.population.dims
    assert inputs.population.sizes["group"] == 3
