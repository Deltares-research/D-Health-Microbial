from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from rasterio.coords import BoundingBox

logger = logging.getLogger(__name__)

# Suffixes we treat as GeoTIFF (read via rioxarray) vs netCDF (read via xarray).
_TIFF_SUFFIXES = {".tif", ".tiff"}
_NETCDF_SUFFIXES = {".nc", ".nc4", ".cdf"}


def _dataset_to_dataarray(ds: xr.Dataset) -> xr.DataArray:
    """Pull the single data variable out of a Dataset.

    The netCDF files this package writes hold exactly one data variable
    (``spatial_ref`` is a coordinate, not a variable). Raise if that
    assumption is violated so callers fail loudly rather than silently
    grabbing the wrong layer.
    """
    data_vars = list(ds.data_vars)
    if len(data_vars) != 1:
        raise ValueError(
            f"expected a single data variable, found {data_vars}. "
            "Open multi-variable netCDF with xarray directly."
        )
    return ds[data_vars[0]]


def load_raster(
    file_path: Path | str,
    *,
    squeeze: bool = True,
    masked: bool = True,
) -> xr.DataArray:
    """Load a raster as an :class:`xarray.DataArray` with CRS attached.

    Auto-detects format by suffix: ``.tif``/``.tiff`` are read with
    :func:`rioxarray.open_rasterio`; ``.nc``/``.nc4``/``.cdf`` with
    :func:`xarray.open_dataset` (``decode_coords="all"`` so the ``.rio``
    accessor recovers the CRS from the ``spatial_ref``/``grid_mapping``).

    Source nodata is converted to ``NaN`` (``masked=True``), matching the
    NaN-nodata convention used throughout the model. The file is read fully
    into memory and closed before returning (avoids Windows file locks when a
    path is re-read or overwritten).

    Returns
    -------
    xr.DataArray
        Dims ``(band, y, x)`` for a multi-band tif, or ``(y, x)`` when
        ``squeeze`` collapses a single band. netCDF arrays keep whatever dims
        they were written with (e.g. ``(group, y, x)``).
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix in _TIFF_SUFFIXES:
        with rioxarray.open_rasterio(file_path, masked=masked) as src:
            da = src.load()
    elif suffix in _NETCDF_SUFFIXES:
        with xr.open_dataset(file_path, decode_coords="all") as ds:
            # rioxarray stores the CRS in a grid-mapping variable (usually
            # ``spatial_ref``). Make sure it's treated as a coordinate — not a
            # data variable — regardless of how the file encoded grid_mapping,
            # so ``.rio.crs`` recovers it and it doesn't look like a 2nd layer.
            gm_vars = {"spatial_ref", "crs"}
            gm_vars |= {ds[v].attrs.get("grid_mapping") for v in ds.data_vars}
            gm_vars = {
                v for v in gm_vars
                if v and v in ds.variables and v not in ds.coords
            }
            if gm_vars:
                ds = ds.set_coords(sorted(gm_vars))
            da = _dataset_to_dataarray(ds).load()
    else:
        raise ValueError(
            f"Unsupported raster suffix {suffix!r} for {file_path}. "
            f"Expected one of {sorted(_TIFF_SUFFIXES | _NETCDF_SUFFIXES)}."
        )

    if squeeze and "band" in da.dims and da.sizes["band"] == 1:
        da = da.squeeze("band", drop=True)
    return da


def _resolve_group_labels(
    da: xr.DataArray, group_names: Sequence[str] | None
) -> list[str]:
    """Pick string labels for a population array's ``group`` dimension.

    Priority: explicit ``group_names`` → per-band descriptions (rioxarray
    surfaces these as the ``long_name`` attr) → positional ``"1".."n"``.
    """
    n = da.sizes["group"]
    if group_names is not None:
        if len(group_names) != n:
            raise ValueError(
                f"group_names has {len(group_names)} entries but the raster has "
                f"{n} bands"
            )
        return [str(g) for g in group_names]

    long_name = da.attrs.get("long_name")
    if isinstance(long_name, (tuple, list)) and len(long_name) == n:
        return [str(g) for g in long_name]

    return [str(i + 1) for i in range(n)]


def load_population(
    file_path: Path | str,
    *,
    group_names: Sequence[str] | None = None,
) -> xr.DataArray:
    """Load the population raster as a DataArray with a labelled ``group`` dim.

    netCDF inputs are expected to already carry a ``group`` dimension (this is
    how :func:`d_health.preprocessing.population.get_population_data` writes
    them). A multi-band GeoTIFF (back-compat) has its ``band`` dimension
    renamed to ``group`` and labelled via :func:`_resolve_group_labels`.
    """
    da = load_raster(file_path, squeeze=False)

    if "group" not in da.dims and "band" in da.dims:
        da = da.rename({"band": "group"})
        da = da.assign_coords(group=_resolve_group_labels(da, group_names))

    if "group" not in da.dims:
        raise ValueError(
            f"population raster {file_path} must have a 'group' dimension "
            "(netCDF) or multiple bands (GeoTIFF); got dims "
            f"{tuple(da.dims)}"
        )

    # Normalise group labels to plain Python strings for .sel(group=...) by name.
    da = da.assign_coords(group=[str(g) for g in da["group"].values])
    return da


def da_to_meta(da: xr.DataArray) -> dict:
    """Derive a rasterio-style ``meta`` dict (transform/crs/bounds/...) from a DataArray.

    This bridges the xarray I/O layer and the numpy numeric core: functions
    like :func:`d_health.geo.get_cell_area` and the concentration step operate
    on a plain georeferencing dict rather than an xarray object.
    """
    left, bottom, right, top = da.rio.bounds()
    if "group" in da.dims:
        count = int(da.sizes["group"])
    elif "band" in da.dims:
        count = int(da.sizes["band"])
    else:
        count = 1
    return {
        "transform": da.rio.transform(),
        "crs": da.rio.crs,
        "bounds": BoundingBox(left, bottom, right, top),
        "width": int(da.rio.width),
        "height": int(da.rio.height),
        "count": count,
    }


def wrap_like(
    values: np.ndarray,
    ref_da: xr.DataArray,
    *,
    name: str,
    group: Sequence[str] | None = None,
) -> xr.DataArray:
    """Wrap a numpy result onto the grid (x/y coords + CRS) of ``ref_da``.

    Used to turn the numeric core's numpy outputs back into georeferenced
    DataArrays for writing. ``values`` may be 2-D ``(y, x)`` or, with
    ``group`` supplied, 3-D ``(group, y, x)``.
    """
    y = ref_da["y"]
    x = ref_da["x"]
    if values.ndim == 2:
        da = xr.DataArray(values, dims=("y", "x"), coords={"y": y, "x": x}, name=name)
    elif values.ndim == 3:
        if group is None:
            raise ValueError("group labels are required to wrap a 3-D array")
        da = xr.DataArray(
            values,
            dims=("group", "y", "x"),
            coords={"group": [str(g) for g in group], "y": y, "x": x},
            name=name,
        )
    else:
        raise ValueError(f"values must be 2-D or 3-D, got {values.ndim}-D")
    return da.rio.write_crs(ref_da.rio.crs)


def from_numpy(
    values: np.ndarray,
    transform,
    crs,
    *,
    name: str,
    group: Sequence[str] | None = None,
    nodata: float | None = None,
) -> xr.DataArray:
    """Build a georeferenced DataArray from a numpy array + affine transform.

    Used by the preprocessing writers, which hold a rasterio ``Affine``
    transform and CRS (not a reference DataArray). Pixel-centre ``x``/``y``
    coordinates are derived from the transform; rotation terms are ignored
    (the WorldPop / GHS-SMOD products are north-up).

    ``values`` is 2-D ``(y, x)`` or, with ``group`` supplied, 3-D
    ``(group, y, x)``.
    """
    if values.ndim == 2:
        height, width = values.shape
    elif values.ndim == 3:
        if group is None:
            raise ValueError("group labels are required to wrap a 3-D array")
        _, height, width = values.shape
    else:
        raise ValueError(f"values must be 2-D or 3-D, got {values.ndim}-D")

    cols = np.arange(width)
    rows = np.arange(height)
    x = transform.c + transform.a * (cols + 0.5)
    y = transform.f + transform.e * (rows + 0.5)

    if values.ndim == 2:
        da = xr.DataArray(values, dims=("y", "x"), coords={"y": y, "x": x}, name=name)
    else:
        da = xr.DataArray(
            values,
            dims=("group", "y", "x"),
            coords={"group": [str(g) for g in group], "y": y, "x": x},
            name=name,
        )

    da = da.rio.write_crs(crs)
    if nodata is not None:
        da = da.rio.write_nodata(nodata)
    return da


def write_netcdf(
    obj: xr.DataArray | xr.Dataset,
    out_path: Path | str,
    *,
    crs=None,
    descriptions: Sequence[str] | None = None,
    name: str | None = None,
) -> Path:
    """Write a DataArray/Dataset to a compressed, CF-georeferenced netCDF.

    The CRS is written via rioxarray (``spatial_ref`` coordinate +
    ``grid_mapping`` attr) so the file round-trips through
    :func:`load_raster` and opens in QGIS/GDAL. Data variables are
    zlib-compressed; float variables get a ``NaN`` ``_FillValue``.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(obj, xr.DataArray):
        if name is not None:
            obj = obj.rename(name)
        elif obj.name is None:
            obj = obj.rename("data")
        if descriptions is not None:
            obj.attrs["long_name"] = tuple(descriptions)
        ds = obj.to_dataset()
    else:
        ds = obj

    if crs is not None:
        ds = ds.rio.write_crs(crs)

    encoding = {}
    for var in ds.data_vars:
        enc = {"zlib": True, "complevel": 4}
        if np.issubdtype(ds[var].dtype, np.floating):
            enc["_FillValue"] = np.nan
        encoding[var] = enc

    ds.to_netcdf(out_path, engine="netcdf4", encoding=encoding)

    n_vars = len(ds.data_vars)
    logger.info("Wrote %s (%d variable(s))", out_path.name, n_vars)
    return out_path
