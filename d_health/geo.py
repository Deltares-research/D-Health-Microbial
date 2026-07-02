from __future__ import annotations

import logging

import rioxarray  # noqa: F401  (registers the .rio accessor)
import utm
import xarray as xr
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, transform_bounds
from rasterio.warp import transform as warp_transform
from rioxarray.exceptions import NoDataInBounds, OneDimensionalRaster

logger = logging.getLogger(__name__)


def get_utm_zone(meta: dict) -> int:
    """EPSG code of the UTM zone covering the raster's centre."""
    bounds = meta["bounds"]
    crs = meta["crs"]

    center_x = (bounds.left + bounds.right) / 2
    center_y = (bounds.top + bounds.bottom) / 2

    if crs.to_epsg() != 4326:
        # Use GDAL's PROJ (via rasterio.warp) rather than pyproj directly: it's
        # the backend already configured under the pixi env, and avoids
        # pyproj's separate PROJ-database lookup.
        lons, lats = warp_transform(crs, "EPSG:4326", [center_x], [center_y])
        center_lon, center_lat = lons[0], lats[0]
    else:
        center_lon, center_lat = center_x, center_y

    _, _, zone_number, hemisphere = utm.from_latlon(center_lat, center_lon)
    if center_lat < 0:
        hemisphere = "S"

    return (32700 if hemisphere == "S" else 32600) + zone_number


def get_cell_area(meta: dict) -> float:
    """Approximate raster cell area in m², via reprojection to UTM."""
    dst_crs = get_utm_zone(meta)
    transform, _, _ = calculate_default_transform(
        meta["crs"],
        dst_crs,
        meta["width"],
        meta["height"],
        *meta["bounds"],
    )
    return transform.a * abs(transform.e)


def _resampling_method(name: str) -> Resampling:
    """Resolve a ``rasterio.enums.Resampling`` member by name (clear error)."""
    try:
        return Resampling[name]
    except KeyError as exc:
        valid = ", ".join(r.name for r in Resampling)
        raise ValueError(f"Unknown resampling {name!r}. Valid: {valid}") from exc


def align_rasters(
    input_da: xr.DataArray,
    target_da: xr.DataArray,
    *,
    resampling: str = "average",
) -> tuple[xr.DataArray, xr.DataArray]:
    """Reproject ``input_da`` onto the grid of ``target_da`` and clip both to the
    input's footprint.

    Reproject-then-clip via rioxarray: ``reproject_match`` puts the input on the
    target's CRS / resolution / extent, then both arrays are clipped to the
    input's bounding box (expressed in the target CRS) so they share the same
    sub-grid — the input footprint intersected with the target. This reproduces
    the windowing the model relied on before the xarray migration.

    Both arrays may be 2-D ``(y, x)`` or carry a leading ``group``/``band`` dim;
    each output mirrors its input's dimensionality. ``NaN`` is the nodata
    convention (matching :func:`d_health.io.load_raster`).

    Parameters
    ----------
    input_da
        Source raster to reproject (carries its own CRS via ``.rio``).
    target_da
        Raster whose grid (CRS, transform, resolution) defines the output grid.
    resampling
        Name of a ``rasterio.enums.Resampling`` member. Pick based on what the
        input represents: ``"average"`` for fractional / mean quantities,
        ``"max"`` for worst-case, ``"bilinear"`` for continuous fields,
        ``"nearest"`` for categorical.

    Returns
    -------
    (aligned_input, clipped_target)
        Both DataArrays sit on the same grid as the target, restricted to the
        input footprint.
    """
    method = _resampling_method(resampling)

    matched = input_da.rio.reproject_match(target_da, resampling=method)

    # Input footprint expressed in the target CRS, used to clip both arrays.
    src_bounds = input_da.rio.bounds()
    if input_da.rio.crs != target_da.rio.crs:
        minx, miny, maxx, maxy = transform_bounds(
            input_da.rio.crs, target_da.rio.crs, *src_bounds
        )
    else:
        minx, miny, maxx, maxy = src_bounds

    try:
        aligned = matched.rio.clip_box(minx, miny, maxx, maxy)
        clipped_target = target_da.rio.clip_box(minx, miny, maxx, maxy)
    except (NoDataInBounds, OneDimensionalRaster) as exc:
        raise ValueError(
            "Input and target rasters do not overlap "
            f"(input bounds in target CRS: {(minx, miny, maxx, maxy)}, "
            f"target bounds: {target_da.rio.bounds()})."
        ) from exc

    logger.info(
        "Aligned input %s and clipped target onto %d × %d grid (resampling=%s)",
        tuple(aligned.shape), aligned.rio.height, aligned.rio.width, resampling,
    )
    return aligned, clipped_target
