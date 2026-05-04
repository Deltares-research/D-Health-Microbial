from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform


def align_flood_and_population(
    flood_path: Path | str,
    population_path: Path | str,
    output_dir: Path | str,
    *,
    resampling: str = "average",
) -> tuple[Path, Path]:
    """Align a fine-resolution flood-depth raster onto the WorldPop 100m grid.

    The flood raster is reprojected onto the population raster's pixel grid
    (CRS, transform, resolution) using ``resampling`` (default: ``"average"``,
    which encodes ``flooded_fraction × mean_depth_when_flooded`` for each
    coarse cell). The population raster is window-clipped to the same bounds.
    Both outputs share an identical grid, so downstream code can do cell-wise
    arithmetic without further reprojection.

    Output extent = the flood raster's footprint reprojected into the
    population CRS, snapped outwards to whole population pixels.

    Parameters
    ----------
    flood_path
        Path to the source flood-depth raster (single band, depth in meters).
    population_path
        Path to a WorldPop raster (any band count) defining the target grid.
    output_dir
        Directory to write the two aligned outputs into. Created if missing.
    resampling
        Name of a ``rasterio.enums.Resampling`` member (e.g. ``"average"``,
        ``"max"``, ``"bilinear"``). Use ``"average"`` for risk-mean exposure;
        ``"max"`` for worst-case.

    Returns
    -------
    (aligned_flood_path, clipped_population_path)
        Both rasters sit on the same grid as ``population_path`` (resolution,
        CRS, transform), restricted to the flood footprint.
    """
    flood_path = Path(flood_path)
    population_path = Path(population_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        resampling_method = Resampling[resampling]
    except KeyError as exc:
        valid = ", ".join(r.name for r in Resampling)
        raise ValueError(
            f"Unknown resampling {resampling!r}. Valid: {valid}"
        ) from exc

    with rasterio.open(flood_path) as flood, rasterio.open(population_path) as pop:
        if flood.crs != pop.crs:
            flood_bounds_in_pop = transform_bounds(flood.crs, pop.crs, *flood.bounds)
        else:
            flood_bounds_in_pop = flood.bounds

        win = (
            from_bounds(*flood_bounds_in_pop, transform=pop.transform)
            .round_offsets(op="floor")
            .round_lengths(op="ceil")
        )
        win = _intersect_window(win, pop.width, pop.height)
        if win.width <= 0 or win.height <= 0:
            raise ValueError(
                "Flood and population rasters do not overlap "
                f"(flood bounds in pop CRS: {flood_bounds_in_pop}, "
                f"pop bounds: {pop.bounds})."
            )

        target_transform = window_transform(win, pop.transform)
        target_height = int(win.height)
        target_width = int(win.width)

        flood_nodata = flood.nodata if flood.nodata is not None else np.nan
        flood_dst = np.full(
            (target_height, target_width), flood_nodata, dtype=np.float32
        )
        reproject(
            source=rasterio.band(flood, 1),
            destination=flood_dst,
            src_transform=flood.transform,
            src_crs=flood.crs,
            src_nodata=flood.nodata,
            dst_transform=target_transform,
            dst_crs=pop.crs,
            dst_nodata=flood_nodata,
            resampling=resampling_method,
        )

        flood_out = output_dir / f"{flood_path.stem}_on_pop_grid.tif"
        flood_profile = {
            "driver": "GTiff",
            "count": 1,
            "dtype": "float32",
            "crs": pop.crs,
            "transform": target_transform,
            "width": target_width,
            "height": target_height,
            "nodata": flood_nodata if not np.isnan(flood_nodata) else None,
            "compress": "deflate",
        }
        with rasterio.open(flood_out, "w", **flood_profile) as dst:
            dst.write(flood_dst, 1)
            dst.descriptions = ("flood_depth_m",)

        pop_data = pop.read(window=win)
        pop_out = output_dir / f"{population_path.stem}_clipped.tif"
        pop_profile = pop.profile.copy()
        pop_profile.update(
            driver="GTiff",
            transform=target_transform,
            width=target_width,
            height=target_height,
            compress="deflate",
        )
        with rasterio.open(pop_out, "w", **pop_profile) as dst:
            dst.write(pop_data)
            if pop.descriptions:
                dst.descriptions = pop.descriptions

    return flood_out, pop_out


def _intersect_window(win: Window, width: int, height: int) -> Window:
    """Clamp ``win`` to the [0, width] × [0, height] image extent."""
    col_off = max(int(win.col_off), 0)
    row_off = max(int(win.row_off), 0)
    col_end = min(int(win.col_off) + int(win.width), width)
    row_end = min(int(win.row_off) + int(win.height), height)
    return Window(col_off, row_off, max(col_end - col_off, 0), max(row_end - row_off, 0))
