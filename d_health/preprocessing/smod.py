from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from rasterio.mask import mask as rio_mask

from d_health.config.preprocessing import GHSSmodConfig
from d_health.io import from_numpy, write_netcdf

logger = logging.getLogger(__name__)

SMOD_CRS = "EPSG:4326"  # 30 arc-second product is published in WGS84 lat/lon

# Urban / Rural reclassification of the GHS-SMOD class codes.
# Water (10) and pixels outside the AOI fall through to 0 (nodata).
URBAN_CLASSES: tuple[int, ...] = (30, 23, 22, 21)
RURAL_CLASSES: tuple[int, ...] = (13, 12, 11)
OUTPUT_NODATA = 0
OUTPUT_CLASSES: dict[int, str] = {1: "urban", 2: "rural"}

__all__ = ["GHSSmodConfig", "get_smod_data"]


def _download_zip(url: str, dest: Path) -> Path:
    """Stream-download a ZIP with atomic rename."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(tmp, "wb") as f:
            written = 0
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
        logger.debug("Wrote %d / %d bytes", written, total)
    tmp.replace(dest)
    logger.info("Saved %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return dest


def _extract_tif(zip_path: Path, tif_name: str, dest_dir: Path) -> Path:
    """Extract a single ``.tif`` member from a ZIP."""
    out = dest_dir / tif_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        # JRC bundles auxiliary files (.aux.xml, .ovr, .txt) alongside the TIF;
        # match by basename to be robust to extra prefixes.
        members = [n for n in z.namelist() if n.endswith(tif_name)]
        if not members:
            tifs = [n for n in z.namelist() if n.lower().endswith(".tif")]
            raise FileNotFoundError(
                f"Expected {tif_name} in {zip_path.name}; got TIFs: {tifs}"
            )
        member = members[0]
        tmp = out.with_suffix(out.suffix + ".part")
        with z.open(member) as src, open(tmp, "wb") as dst:
            while chunk := src.read(1 << 16):
                dst.write(chunk)
        tmp.replace(out)
    logger.info("Extracted %s", out.name)
    return out


def _normalize_clip(clip: Any, target_crs: str) -> list[dict] | None:
    """Resolve a user-supplied clip into GeoJSON-like geometries in
    ``target_crs``.

    Accepts:
      - None (no clipping)
      - shapely geometry (anything with ``__geo_interface__``)
      - GeoJSON-style dict (Polygon, Feature, FeatureCollection, ...)
      - geopandas.GeoDataFrame / GeoSeries (auto-reprojected to ``target_crs``)
      - 4-tuple/list of bounds ``(xmin, ymin, xmax, ymax)`` in ``target_crs``
    """
    if clip is None:
        return None

    # GeoDataFrame / GeoSeries — duck-typed via .to_crs + .crs
    if hasattr(clip, "to_crs") and hasattr(clip, "crs"):
        crs = getattr(clip, "crs", None)
        if crs is not None and str(crs).upper() != target_crs.upper():
            clip = clip.to_crs(target_crs)
        geoms = clip.geometry if hasattr(clip, "geometry") else clip
        return [g.__geo_interface__ for g in geoms if g is not None]

    # Bounds: (xmin, ymin, xmax, ymax)
    if isinstance(clip, (tuple, list)) and len(clip) == 4 and all(
        isinstance(v, (int, float)) for v in clip
    ):
        xmin, ymin, xmax, ymax = clip
        return [{
            "type": "Polygon",
            "coordinates": [[
                [xmin, ymin], [xmax, ymin],
                [xmax, ymax], [xmin, ymax], [xmin, ymin],
            ]],
        }]

    # Shapely (or anything implementing __geo_interface__)
    if hasattr(clip, "__geo_interface__"):
        return [clip.__geo_interface__]

    # Raw GeoJSON dict
    if isinstance(clip, dict) and clip.get("type") in {
        "Polygon", "MultiPolygon", "Feature", "FeatureCollection", "GeometryCollection",
    }:
        if clip["type"] == "FeatureCollection":
            return [f["geometry"] for f in clip["features"]]
        if clip["type"] == "Feature":
            return [clip["geometry"]]
        return [clip]

    raise TypeError(
        f"Unsupported clip type: {type(clip).__name__}. Expected None, shapely "
        "geometry, GeoJSON dict, GeoDataFrame/GeoSeries, or bounds tuple "
        f"(xmin, ymin, xmax, ymax) in {target_crs}."
    )


def _reclassify(arr: np.ndarray) -> np.ndarray:
    """Remap GHS-SMOD codes to {0 nodata, 1 urban, 2 rural}.

    Any code not in ``URBAN_CLASSES`` or ``RURAL_CLASSES`` — including water
    (10), the source nodata value, and the AOI fill produced by
    ``rasterio.mask.mask`` — collapses to ``OUTPUT_NODATA``.
    """
    out = np.full(arr.shape, OUTPUT_NODATA, dtype=np.uint8)
    out[np.isin(arr, URBAN_CLASSES)] = 1
    out[np.isin(arr, RURAL_CLASSES)] = 2
    return out


def get_smod_data(
    output_path: Path | str,
    *,
    clip: Any = None,
    cfg: GHSSmodConfig = GHSSmodConfig(),
) -> Path:
    """Download GHS-SMOD from JRC, clip to an AOI, and reclassify to Urban /
    Rural.

    Pipeline: stream the global ZIP from the JRC open-data server, extract the
    GeoTIFF, mask to ``clip``, then remap the SMOD class codes into a 3-value
    uint8 raster:

    - ``1`` — Urban  (SMOD 30, 23, 22, 21)
    - ``2`` — Rural  (SMOD 13, 12, 11)
    - ``0`` — nodata (water=10, source nodata, pixels outside the AOI)

    The downloaded ZIP and extracted full-globe TIF live in a temporary
    directory and are removed before this function returns; only the
    reclassified raster persists at ``output_path``.

    Parameters
    ----------
    output_path : Path | str
        Full path of the reclassified netCDF to write (a ``.tif``/``.tiff``
        suffix is replaced with ``.nc``). Parent directories are created if
        they don't exist.
    clip : optional
        Region of interest. ``None`` reclassifies the full global raster.
        Accepts: a shapely geometry, a GeoJSON dict, a GeoDataFrame/GeoSeries
        (auto-reprojected to EPSG:4326), or a bounds tuple
        ``(xmin, ymin, xmax, ymax)`` in EPSG:4326.
    cfg : GHSSmodConfig
        Selects which SMOD product to fetch (epoch, release, version, ...).

    Returns
    -------
    Path
        Path to the reclassified Urban/Rural netCDF (``output_path`` with a
        ``.nc`` suffix).
    """
    out_path = Path(output_path)
    if out_path.suffix.lower() in {".tif", ".tiff"}:
        out_path = out_path.with_suffix(".nc")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clip_geoms = _normalize_clip(clip, SMOD_CRS)
    logger.info(
        "GHS-SMOD %s E%d (%s, %s) — clip=%s",
        cfg.release, cfg.epoch, cfg.crs_code, cfg.resolution,
        "yes" if clip_geoms else "no",
    )

    with tempfile.TemporaryDirectory(prefix="d_health_smod_") as td:
        tmpdir = Path(td)
        zip_path = _download_zip(
            cfg.zip_url,
            tmpdir / f"{cfg.stem}_{cfg.version_filename}.zip",
        )
        src_tif = _extract_tif(zip_path, cfg.tif_name, tmpdir)

        with rasterio.open(src_tif) as src:
            if clip_geoms is None:
                data = src.read(1)
                transform = src.transform
                height, width = src.height, src.width
            else:
                src_nodata = src.nodata if src.nodata is not None else 0
                data, transform = rio_mask(
                    src, clip_geoms, crop=True, filled=True,
                    nodata=src_nodata, all_touched=True,
                )
                data = data[0]  # single-band product
                height, width = data.shape
            src_crs = src.crs

    reclassified = _reclassify(data)
    del data

    urban_rural = from_numpy(
        reclassified,
        transform,
        src_crs,
        name="urban_rural",
        nodata=OUTPUT_NODATA,
    )
    urban_rural.attrs.update(
        {f"class_{code}": label for code, label in OUTPUT_CLASSES.items()}
    )
    write_netcdf(urban_rural, out_path, descriptions=("urban_rural",))

    counts = {
        "urban": int((reclassified == 1).sum()),
        "rural": int((reclassified == 2).sum()),
        "nodata": int((reclassified == 0).sum()),
    }
    logger.info(
        "Wrote %s (%d × %d, urban=%d rural=%d nodata=%d, %.2f MB)",
        out_path.name, height, width,
        counts["urban"], counts["rural"], counts["nodata"],
        out_path.stat().st_size / 1e6,
    )
    return out_path
