from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from rasterio.mask import mask as rio_mask

from d_health.config.preprocessing import (
    ADULT_AGE_BINS,
    CHILD_AGE_BINS,
    WorldPopConfig,
)
from d_health.io import from_numpy, write_raster

logger = logging.getLogger(__name__)

WORLDPOP_BASE = "https://data.worldpop.org/GIS/AgeSex_structures"
WORLDPOP_CRS = "EPSG:4326"

SEXES: tuple[str, ...] = ("m", "f")

__all__ = ["WorldPopConfig", "CHILD_AGE_BINS", "ADULT_AGE_BINS", "get_population_data"]


def _build_url(country: str, year: int, age: str, sex: str, cfg: WorldPopConfig) -> str:
    """Build the WorldPop download URL for a per-age, per-sex raster.

    Two product layouts are supported (selected by ``cfg.layout``):

    ``global1_2000_2020`` (default)
        Flat path ``{series}/{year}/{ISO}/`` with filenames
        ``{iso}_{sex}_{age}_{year}_constrained.tif`` (the ``_constrained``
        suffix is dropped for the unconstrained variant), e.g.
        ``moz_f_0_2020_constrained.tif``.

    ``global2_2015_2030``
        Nested path ``{series}/{release}/{year}/{ISO}/{version}/{resolution}/
        {type_dir}/`` with filenames ``{iso}_{sex}_{age}_{year}_{type_code}_
        {resolution}_{release}_{version}.tif``, e.g.
        ``moz_f_00_2020_CN_100m_R2025A_v1.tif``.
    """
    iso_upper = country.upper()
    iso_lower = country.lower()
    sex_lower = sex.lower()

    if cfg.layout == "global1_2000_2020":
        suffix = "_constrained" if cfg.constrained else ""
        filename = f"{iso_lower}_{sex_lower}_{age}_{year}{suffix}.tif"
        return f"{WORLDPOP_BASE}/{cfg.series}/{year}/{iso_upper}/{filename}"

    filename = (
        f"{iso_lower}_{sex_lower}_{age}_{year}_{cfg.type_code}_"
        f"{cfg.resolution}_{cfg.release}_{cfg.version}.tif"
    )
    return (
        f"{WORLDPOP_BASE}/{cfg.series}/{cfg.release}/{year}/{iso_upper}/"
        f"{cfg.version}/{cfg.resolution}/{cfg.type_dir}/{filename}"
    )


def _download_raster(url: str, dest: Path) -> Path | None:
    """Stream-download a single raster. Returns None on 404."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("GET %s", url)
    with requests.get(url, stream=True, timeout=120) as r:
        if r.status_code == 404:
            logger.debug("404 %s", url)
            return None
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 15):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)
    logger.debug("Saved %s (%d bytes)", dest.name, dest.stat().st_size)
    return dest


def _normalize_clip(clip: Any) -> list[dict] | None:
    """Resolve a user-supplied clip into a list of GeoJSON-like geometries
    in WorldPop's CRS (EPSG:4326).

    Accepts:
      - None (no clipping)
      - shapely geometry (anything with ``__geo_interface__``)
      - GeoJSON-style dict
      - geopandas.GeoDataFrame / GeoSeries (auto-reprojected to EPSG:4326)
      - 4-tuple/list of bounds (xmin, ymin, xmax, ymax) in EPSG:4326
    """
    if clip is None:
        return None

    # GeoDataFrame / GeoSeries — duck-typed via .to_crs + .geometry/.values
    if hasattr(clip, "to_crs") and hasattr(clip, "crs"):
        crs = getattr(clip, "crs", None)
        if crs is not None and str(crs).upper() != WORLDPOP_CRS:
            clip = clip.to_crs(WORLDPOP_CRS)
        geoms = clip.geometry if hasattr(clip, "geometry") else clip
        return [g.__geo_interface__ for g in geoms if g is not None]

    # Bounds: (xmin, ymin, xmax, ymax)
    if (
        isinstance(clip, (tuple, list))
        and len(clip) == 4
        and all(isinstance(v, (int, float)) for v in clip)
    ):
        xmin, ymin, xmax, ymax = clip
        return [
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [xmin, ymin],
                        [xmax, ymin],
                        [xmax, ymax],
                        [xmin, ymax],
                        [xmin, ymin],
                    ]
                ],
            }
        ]

    # Shapely geometry (or anything implementing __geo_interface__)
    if hasattr(clip, "__geo_interface__"):
        return [clip.__geo_interface__]

    # Raw GeoJSON dict
    if isinstance(clip, dict) and clip.get("type") in {
        "Polygon",
        "MultiPolygon",
        "Feature",
        "FeatureCollection",
        "GeometryCollection",
    }:
        if clip["type"] == "FeatureCollection":
            return [f["geometry"] for f in clip["features"]]
        if clip["type"] == "Feature":
            return [clip["geometry"]]
        return [clip]

    raise TypeError(
        f"Unsupported clip type: {type(clip).__name__}. Expected None, shapely "
        "geometry, GeoJSON dict, GeoDataFrame/GeoSeries, or bounds tuple "
        "(xmin, ymin, xmax, ymax)."
    )


def _read_one(path: Path, clip_geoms: list[dict] | None) -> tuple[np.ndarray, dict]:
    """Open a raster, optionally crop to ``clip_geoms``, return data + profile."""
    with rasterio.open(path) as src:
        if clip_geoms is None:
            data = src.read(1)
            transform = src.transform
            profile = src.profile.copy()
        else:
            data, transform = rio_mask(
                src, clip_geoms, crop=True, filled=True, nodata=0, all_touched=True
            )
            data = data[0]
            profile = src.profile.copy()
            profile.update(
                transform=transform, height=data.shape[0], width=data.shape[1]
            )
    data = data.astype(np.float32)
    data[data < 0] = 0
    return data, profile


def get_population_data(
    country: str,
    year: int,
    output_path: Path | str,
    *,
    clip: Any = None,
    cfg: WorldPopConfig = WorldPopConfig(),
    child_ages: Sequence[str] | None = None,
    adult_ages: Sequence[str] | None = None,
) -> Path:
    """Download age- and sex-disaggregated WorldPop rasters and aggregate them
    into a netCDF with a labelled ``group`` dimension.

    Groups: ``children`` (0-9 yr), ``adults`` (10+ yr), ``total``.

    The per-age rasters are downloaded into a temporary directory, clipped (if
    a ``clip`` geometry is supplied) and summed in memory; only the final
    combined raster is persisted to ``output_path``. Each source file is
    deleted right after it's consumed, so peak temp-disk use stays small.

    Parameters
    ----------
    country : str
        ISO3 country code (case-insensitive), e.g. ``"SUR"``.
    year : int
        Year in the 2015-2030 R2025A coverage.
    output_path : Path | str
        Full path of the combined raster to write. **The suffix chooses the
        format**: ``.nc`` writes netCDF, ``.tif`` a multi-band GeoTIFF (see
        :func:`d_health.io.write_raster`). Parent directories are created if
        they don't exist.
    clip : optional
        Region of interest. If provided, every per-age raster is masked to
        this geometry before summing, and the final output covers only this
        region. Accepts: ``None`` (no clip; full country), a shapely geometry,
        a GeoJSON dict, a GeoDataFrame/GeoSeries (auto-reprojected to
        EPSG:4326), or a bounds tuple ``(xmin, ymin, xmax, ymax)`` in
        EPSG:4326.
    cfg : WorldPopConfig
        Product layout / series / release / constrained-vs-unconstrained
        settings. The default fetches the ``Global_2000_2020_Constrained``
        2020 product.
    child_ages, adult_ages : Sequence[str], optional
        Age-bin codes that map to the children and adults output bands. When
        ``None`` (the default) they are taken from ``cfg`` (``cfg.child_age_bins``
        / ``cfg.adult_age_bins``), which already match the active layout's
        age-code padding and adult cap. Pass explicit codes only to override.

    Returns
    -------
    Path
        ``output_path``, unchanged.
    """
    if child_ages is None:
        child_ages = cfg.child_age_bins
    if adult_ages is None:
        adult_ages = cfg.adult_age_bins
    child_ages = tuple(child_ages)
    adult_ages = tuple(adult_ages)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clip_geoms = _normalize_clip(clip)
    n_expected = len(child_ages + adult_ages) * len(SEXES)
    logger.info(
        "Fetching WorldPop %s %d (%s, %s) — %d files, clip=%s",
        country.upper(),
        year,
        cfg.series,
        cfg.type_dir,
        n_expected,
        "yes" if clip_geoms else "no",
    )
    missing: list[str] = []

    def fetch_group(
        ages: Sequence[str], label: str, tmpdir: Path
    ) -> tuple[np.ndarray, dict]:
        n = len(ages) * len(SEXES)
        logger.info(
            "Downloading %s rasters (%d files: %d age bins × %d sexes)",
            label,
            n,
            len(ages),
            len(SEXES),
        )
        total: np.ndarray | None = None
        profile: dict | None = None
        for age in ages:
            for sex in SEXES:
                url = _build_url(country, year, age, sex, cfg)
                dest = tmpdir / url.rsplit("/", 1)[-1]
                path = _download_raster(url, dest)
                if path is None:
                    missing.append(url)
                    continue
                data, prof = _read_one(path, clip_geoms)
                path.unlink(missing_ok=True)
                if total is None:
                    total = data
                    profile = prof
                else:
                    total += data
        if total is None or profile is None:
            first_missing = missing[0] if missing else "(no urls?)"
            raise RuntimeError(
                f"No {label} rasters could be downloaded for {country} {year}. "
                f"All requests returned 404. First: {first_missing}"
            )
        logger.info("Aggregated %s: %s, sum=%.0f", label, total.shape, total.sum())
        return total, profile

    with tempfile.TemporaryDirectory(prefix="d_health_pop_") as td:
        tmpdir = Path(td)
        children, profile = fetch_group(child_ages, "child", tmpdir)
        adults, _ = fetch_group(adult_ages, "adult", tmpdir)

    total = children + adults

    data = np.stack(
        [
            children.astype(np.float32),
            adults.astype(np.float32),
            total.astype(np.float32),
        ],
        axis=0,
    )
    population = from_numpy(
        data,
        profile["transform"],
        profile["crs"],
        name="population",
        group=("children", "adults", "total"),
    )
    write_raster(
        population,
        out_path,
        descriptions=("children_0_9", "adults_10_plus", "total"),
        units="people",
    )

    if missing:
        logger.warning(
            "%d of %d rasters were missing (404). Output bands sum the available ones.",
            len(missing),
            n_expected,
        )
    logger.info("Wrote %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)

    return out_path
