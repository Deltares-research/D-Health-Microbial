"""Every raster this package writes must open as georeferenced in GDAL/QGIS.

These assertions are what separate "the CRS is in the file somewhere" from
"a GIS can actually place the pixels". They failed before the grid_mapping
fix in d_health/io.py.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
import xarray as xr
from rasterio.crs import CRS
from rasterio.transform import from_origin

from d_health.io import from_numpy, load_population, write_netcdf

TRANSFORM = from_origin(west=200000.0, north=600000.0, xsize=100.0, ysize=100.0)
CRS_UTM = CRS.from_epsg(32621)


def float_2d():
    """A plain 2-D float layer, like pathogen_conc."""
    values = np.arange(16 * 16, dtype=np.float32).reshape(16, 16)
    return from_numpy(values, TRANSFORM, CRS_UTM, name="pathogen_conc")


def int_2d():
    """A 2-D integer layer, like flood_classes (0 = dry is a real class,
    so there is deliberately no nodata)."""
    values = (np.arange(16 * 16, dtype=np.int16) % 5).reshape(16, 16)
    return from_numpy(values, TRANSFORM, CRS_UTM, name="flood_classes")


def grouped_3d():
    """A 3-D layer stacked along the labelled ``group`` dim, like risk."""
    data = np.stack([np.full((16, 16), v, dtype=np.float32) for v in (1.0, 2.0, 3.0)])
    return from_numpy(
        data,
        TRANSFORM,
        CRS_UTM,
        name="population",
        group=("children", "adults", "total"),
    )


def open_with_gdal(path):
    """Open a file the way a GIS would.

    GDAL may expose a multi-dimensional netCDF variable as a subdataset rather
    than as bands on the top-level dataset; follow the first one when that
    happens so the test reflects what QGIS shows the user.
    """
    src = rasterio.open(path)
    if src.count == 0 and src.subdatasets:
        sub = src.subdatasets[0]
        src.close()
        src = rasterio.open(sub)
    return src


@pytest.mark.parametrize("factory", [float_2d, int_2d, grouped_3d])
def test_gdal_reads_crs_and_transform(tmp_path, factory):
    da = factory()
    path = write_netcdf(da, tmp_path / "layer.nc")

    with open_with_gdal(path) as src:
        assert src.crs == CRS_UTM
        assert src.transform == TRANSFORM


def test_crs_recovered_without_the_load_raster_fallback(tmp_path):
    """load_raster hand-promotes spatial_ref to a coordinate, which hid this bug.
    Plain xarray must recover the CRS on its own."""
    path = write_netcdf(float_2d(), tmp_path / "conc.nc")

    with xr.open_dataset(path, decode_coords="all") as ds:
        assert ds["pathogen_conc"].rio.crs == CRS_UTM
        assert ds["pathogen_conc"].rio.transform() == TRANSFORM


def test_data_variable_carries_grid_mapping(tmp_path):
    path = write_netcdf(float_2d(), tmp_path / "conc.nc")

    with xr.open_dataset(path, decode_coords="all") as ds:
        var = ds["pathogen_conc"]
        grid_mapping = var.encoding.get("grid_mapping") or var.attrs.get("grid_mapping")
        assert grid_mapping == "spatial_ref"


def test_coordinate_variables_are_cf_compliant(tmp_path):
    path = write_netcdf(float_2d(), tmp_path / "conc.nc")

    with xr.open_dataset(path, decode_coords="all") as ds:
        assert ds["x"].attrs["standard_name"] == "projection_x_coordinate"
        assert ds["y"].attrs["standard_name"] == "projection_y_coordinate"
        assert ds["x"].attrs["units"] == "metre"
        # CF forbids _FillValue on a coordinate variable.
        assert "_FillValue" not in ds["x"].encoding
        assert "_FillValue" not in ds["y"].encoding
        assert ds.attrs["Conventions"].startswith("CF-")


def test_units_are_written(tmp_path):
    path = write_netcdf(float_2d(), tmp_path / "conc.nc", units="CFU/100mL")

    with xr.open_dataset(path, decode_coords="all") as ds:
        assert ds["pathogen_conc"].attrs["units"] == "CFU/100mL"


def test_long_name_is_a_single_string(tmp_path):
    """CF requires a scalar long_name; multi-layer descriptions go elsewhere."""
    single = write_netcdf(
        float_2d(), tmp_path / "one.nc", descriptions=("ecoli_per_100ml",)
    )
    many = write_netcdf(
        grouped_3d(),
        tmp_path / "many.nc",
        descriptions=("children_0_9", "adults_10_plus", "total"),
    )

    with xr.open_dataset(single, decode_coords="all") as ds:
        assert ds["pathogen_conc"].attrs["long_name"] == "ecoli_per_100ml"

    with xr.open_dataset(many, decode_coords="all") as ds:
        assert isinstance(ds["population"].attrs.get("long_name", ""), str)
        assert ds["population"].attrs["group_descriptions"] == (
            "children_0_9, adults_10_plus, total"
        )


def test_group_labels_still_roundtrip(tmp_path):
    path = write_netcdf(grouped_3d(), tmp_path / "pop.nc")
    back = load_population(path)

    assert list(map(str, back["group"].values)) == ["children", "adults", "total"]
    assert np.allclose(back.sel(group="adults").values, 2.0, equal_nan=True)
    assert back.rio.crs == CRS_UTM
