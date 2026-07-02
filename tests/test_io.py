"""Round-trip tests for the xarray/rioxarray netCDF I/O."""
from __future__ import annotations

import numpy as np
from rasterio.crs import CRS
from rasterio.transform import from_origin

from d_health.io import da_to_meta, from_numpy, load_population, load_raster, write_netcdf


def _transform_crs():
    return from_origin(west=200000.0, north=600000.0, xsize=100.0, ysize=100.0), CRS.from_epsg(32621)


def test_write_then_load_roundtrip_2d(tmp_path):
    transform, crs = _transform_crs()
    values = np.arange(16 * 16, dtype=np.float32).reshape(16, 16)
    da = from_numpy(values, transform, crs, name="emissions")

    path = write_netcdf(da, tmp_path / "emissions.nc")
    assert path.suffix == ".nc"

    back = load_raster(path)
    assert np.allclose(back.values, values, equal_nan=True)
    assert back.rio.crs == crs
    assert back.rio.transform() == transform


def test_write_then_load_population_preserves_group_labels(tmp_path):
    transform, crs = _transform_crs()
    data = np.stack([
        np.full((16, 16), 1.0, dtype=np.float32),
        np.full((16, 16), 2.0, dtype=np.float32),
        np.full((16, 16), 3.0, dtype=np.float32),
    ])
    da = from_numpy(data, transform, crs, name="population", group=("children", "adults", "total"))

    path = write_netcdf(da, tmp_path / "pop.nc")
    back = load_population(path)

    assert "group" in back.dims
    assert list(map(str, back["group"].values)) == ["children", "adults", "total"]
    assert np.allclose(back.sel(group="adults").values, 2.0, equal_nan=True)
    assert back.rio.crs == crs


def test_da_to_meta_matches_grid(tmp_path):
    transform, crs = _transform_crs()
    da = from_numpy(np.zeros((16, 16), dtype=np.float32), transform, crs, name="x")
    meta = da_to_meta(da)
    assert meta["width"] == 16
    assert meta["height"] == 16
    assert meta["count"] == 1
    assert meta["crs"] == crs
    assert meta["transform"] == transform
