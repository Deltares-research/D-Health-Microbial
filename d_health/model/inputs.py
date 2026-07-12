from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import xarray as xr

from d_health.config.run import EventConfig, ExposureConfig
from d_health.geo import align_rasters
from d_health.io import da_to_meta, load_population, load_raster

logger = logging.getLogger(__name__)


@dataclass
class ModelInputs:
    """All input arrays + the common-grid georeferencing metadata.

    After ``load_inputs`` runs, ``flood``, ``population``, and ``urban_rural``
    all sit on the same grid (population's resolution / CRS, intersected with
    the flood footprint). ``flood_meta`` describes that common grid.

    The numeric core operates on numpy, so ``flood`` and ``urban_rural`` are
    exposed as plain 2-D arrays. ``population`` stays an
    :class:`xarray.DataArray` with a labelled ``group`` dimension so callers
    select a layer by name (``population.sel(group=...)``) rather than by band
    index.

    Not a Pydantic model because the fields are numpy/xarray objects and we
    don't need schema validation here — ``load_inputs`` produces this directly.
    """

    flood: np.ndarray  # (rows, cols); flood depth in m, >0 flooded, 0/NaN dry
    flood_meta: dict  # transform / crs / bounds / width / height / count
    population: xr.DataArray  # (group, rows, cols); labelled group dimension
    urban_rural: np.ndarray  # (rows, cols); 1=urban, 2=rural, 0=nodata


def load_inputs(exposure: ExposureConfig, event: EventConfig) -> ModelInputs:
    """Load the three input rasters and align them onto a common grid.

    The flood forcing comes from ``event.flood_depth_map``; the population and
    urban/rural rasters come from ``exposure``.

    Source rasters typically come in at different CRS / resolution /
    footprint (e.g. WorldPop at 100 m EPSG:4326, GHS-SMOD at 1 km
    EPSG:4326, a flood map at 10 m UTM). The model downstream assumes they
    share a grid, so this loader uses :func:`d_health.geo.align_rasters` to
    reproject flood and urban_rural onto population's grid, intersected with
    the flood footprint.

    Flood depth uses the positive-depth convention throughout the model:
    ``> 0`` flooded (magnitude is the water depth in metres), ``0`` or ``NaN``
    dry. The input raster is expected to already follow this convention.
    """
    flood_da = load_raster(event.flood_depth_map)
    population_da = load_population(exposure.population)
    urban_rural_da = load_raster(exposure.urban_rural)

    if "group" not in population_da.dims:
        raise ValueError(
            f"population raster {exposure.population} must have a 'group' "
            f"dimension; got dims {tuple(population_da.dims)}"
        )

    # Common grid = population's CRS / resolution, clipped to flood footprint.
    # 'average' is right for flood (depths get area-averaged into coarser cells).
    flood_da, population_da = align_rasters(
        flood_da, population_da, resampling="average"
    )

    # Reproject urban_rural onto that common grid with 'nearest' so the
    # categorical codes (1=urban, 2=rural, 0=nodata) survive resampling.
    #
    # align_rasters clips *both* returned arrays to the input's footprint, so
    # this call can shrink the grid again — to the flood ∩ urban_rural overlap.
    # Keep that clipped flood (rather than discarding it) and pull population
    # back onto the same sub-grid, otherwise the three arrays silently end up on
    # different grids whenever urban_rural covers less ground than the flood map.
    urban_rural_da, flood_da = align_rasters(
        urban_rural_da, flood_da, resampling="nearest"
    )
    # flood_da already sits on population's grid, so its x/y are a subset of
    # population's: select (not resample) — population holds *counts*, and
    # resampling an extensive quantity would invent or destroy people.
    population_da = population_da.sel(
        x=flood_da["x"], y=flood_da["y"], method="nearest"
    )

    flood = flood_da.values.astype(np.float32)
    flood_meta = da_to_meta(flood_da)

    # align_rasters writes NaN for nodata; coerce to 0 and cast to int for
    # the equality comparisons downstream.
    urban_rural = np.where(
        np.isnan(urban_rural_da.values), 0, urban_rural_da.values
    ).astype(np.int8)

    # The positive-depth convention is what the whole model assumes; a flood map
    # built by differencing a water surface against a DEM carries negatives on
    # dry high ground. Left alone they yield a negative concentration, a negative
    # dose, and a *negative risk*, which np.nansum then quietly subtracts from
    # the totals. Treat them as dry, and say so.
    negative = flood < 0.0  # False for NaN
    n_negative = int(negative.sum())
    if n_negative:
        logger.warning(
            "flood map has %d negative-depth cell(s) (min %.3f m); clipping to 0 "
            "(treated as dry). Flood depth must be positive — check the raster's "
            "sign convention.",
            n_negative,
            float(flood[negative].min()),
        )
        flood = np.where(negative, 0.0, flood).astype(np.float32)

    _check_common_grid(flood, population_da, urban_rural, exposure, event)

    logger.info(
        "Loaded inputs: flood %s, population %s (groups: %s), urban_rural %s",
        flood.shape,
        population_da.shape[1:],
        list(population_da["group"].values),
        urban_rural.shape,
    )
    return ModelInputs(
        flood=flood,
        flood_meta=flood_meta,
        population=population_da,
        urban_rural=urban_rural,
    )


def _check_common_grid(
    flood: np.ndarray,
    population: xr.DataArray,
    urban_rural: np.ndarray,
    exposure: ExposureConfig,
    event: EventConfig,
) -> None:
    """Assert the invariant ``ModelInputs`` documents: all three share one grid.

    The numeric core indexes these arrays against each other positionally
    (``sani[urban_rural == 1]``, ``risk * population_band``), so a shape
    mismatch surfaces several frames away as an opaque ``IndexError`` about
    boolean axes. Fail here instead, naming the raster that doesn't fit.
    """
    expected = flood.shape
    mismatched = {
        str(event.flood_depth_map): flood.shape,
        str(exposure.population): population.shape[1:],
        str(exposure.urban_rural): urban_rural.shape,
    }
    if len(set(mismatched.values())) == 1:
        return
    detail = "\n".join(f"  {shape}  {path}" for path, shape in mismatched.items())
    raise ValueError(
        "Input rasters do not share a common grid after alignment "
        f"(expected {expected} for all three):\n{detail}\n"
        "This usually means one raster's footprint does not cover the others — "
        "check that the urban/rural and population rasters span the flood map's "
        "extent."
    )
