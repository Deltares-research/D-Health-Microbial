from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

logger = logging.getLogger(__name__)


def align_rasters(
    input_path: Path | str,
    target_path: Path | str,
    output_dir: Path | str,
    *,
    resampling: str = "average",
    aligned_input_name: str | None = None,
    clipped_target_name: str | None = None,
) -> tuple[Path, Path]:
    """Reproject ``input_path`` onto the grid of ``target_path`` and clip
    ``target_path`` to the overlap.

    The input raster is reprojected onto the target raster's pixel grid
    (CRS, transform, resolution) using ``resampling``. The target raster is
    window-clipped to the same bounds. Both outputs share an identical grid,
    so downstream code can do cell-wise arithmetic without further
    reprojection.

    Output extent = the input raster's footprint reprojected into the target
    CRS, snapped outwards to whole target pixels.

    Parameters
    ----------
    input_path
        Path to the raster to reproject (any band count).
    target_path
        Path to the raster whose grid (CRS, transform, resolution) defines
        the output grid.
    output_dir
        Directory to write the two aligned outputs into. Created if missing.
    resampling
        Name of a ``rasterio.enums.Resampling`` member. Pick based on what
        the input represents: ``"average"`` for fractional / mean quantities,
        ``"max"`` for worst-case, ``"bilinear"`` for continuous fields,
        ``"nearest"`` for categorical.
    aligned_input_name
        Filename for the reprojected input. Defaults to
        ``f"{input_path.stem}_aligned.tif"``.
    clipped_target_name
        Filename for the clipped target. Defaults to
        ``f"{target_path.stem}_clipped.tif"``.

    Returns
    -------
    (aligned_input_path, clipped_target_path)
        Both rasters sit on the same grid as ``target_path`` (resolution,
        CRS, transform), restricted to the input footprint.
    """
    input_path = Path(input_path)
    target_path = Path(target_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        resampling_method = Resampling[resampling]
    except KeyError as exc:
        valid = ", ".join(r.name for r in Resampling)
        raise ValueError(
            f"Unknown resampling {resampling!r}. Valid: {valid}"
        ) from exc

    logger.info(
        "Aligning %s onto grid of %s (resampling=%s)",
        input_path.name, target_path.name, resampling,
    )
    with rasterio.open(input_path) as src, rasterio.open(target_path) as tgt:
        if src.crs != tgt.crs:
            src_bounds_in_tgt = transform_bounds(src.crs, tgt.crs, *src.bounds)
            logger.debug("Reprojected input bounds %s → %s", src.crs, tgt.crs)
        else:
            src_bounds_in_tgt = src.bounds

        win = (
            from_bounds(*src_bounds_in_tgt, transform=tgt.transform)
            .round_offsets(op="floor")
            .round_lengths(op="ceil")
        )
        win = _intersect_window(win, tgt.width, tgt.height)
        if win.width <= 0 or win.height <= 0:
            raise ValueError(
                "Input and target rasters do not overlap "
                f"(input bounds in target CRS: {src_bounds_in_tgt}, "
                f"target bounds: {tgt.bounds})."
            )

        target_transform = window_transform(win, tgt.transform)
        target_height = int(win.height)
        target_width = int(win.width)
        logger.debug(
            "Target grid: %d × %d @ %s in %s",
            target_height, target_width, tgt.res, tgt.crs,
        )

        src_nodata = src.nodata if src.nodata is not None else np.nan
        src_indexes = list(src.indexes)
        input_dst = np.full(
            (src.count, target_height, target_width), src_nodata, dtype=np.float32
        )
        reproject(
            source=rasterio.band(src, src_indexes),
            destination=input_dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=target_transform,
            dst_crs=tgt.crs,
            dst_nodata=src_nodata,
            resampling=resampling_method,
        )

        input_out = output_dir / (
            aligned_input_name or f"{input_path.stem}_aligned.tif"
        )
        input_profile = {
            "driver": "GTiff",
            "count": src.count,
            "dtype": "float32",
            "crs": tgt.crs,
            "transform": target_transform,
            "width": target_width,
            "height": target_height,
            "nodata": src_nodata if not np.isnan(src_nodata) else None,
            "compress": "deflate",
        }
        with rasterio.open(input_out, "w", **input_profile) as dst:
            dst.write(input_dst)
            if src.descriptions and any(src.descriptions):
                dst.descriptions = src.descriptions

        tgt_data = tgt.read(window=win)
        target_out = output_dir / (
            clipped_target_name or f"{target_path.stem}_clipped.tif"
        )
        tgt_profile = tgt.profile.copy()
        tgt_profile.update(
            driver="GTiff",
            transform=target_transform,
            width=target_width,
            height=target_height,
            compress="deflate",
        )
        with rasterio.open(target_out, "w", **tgt_profile) as dst:
            dst.write(tgt_data)
            if tgt.descriptions:
                dst.descriptions = tgt.descriptions

    logger.info("Wrote aligned input:  %s", input_out)
    logger.info("Wrote clipped target: %s", target_out)
    return input_out, target_out


def _intersect_window(win: Window, width: int, height: int) -> Window:
    """Clamp ``win`` to the [0, width] × [0, height] image extent."""
    col_off = max(int(win.col_off), 0)
    row_off = max(int(win.row_off), 0)
    col_end = min(int(win.col_off) + int(win.width), width)
    row_end = min(int(win.row_off) + int(win.height), height)
    return Window(col_off, row_off, max(col_end - col_off, 0), max(row_end - row_off, 0))
