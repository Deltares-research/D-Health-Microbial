from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import rasterio
import requests
from rasterio.mask import mask as rio_mask

WORLDPOP_BASE = "https://data.worldpop.org/GIS/AgeSex_structures"
WORLDPOP_CRS = "EPSG:4326"

CHILD_AGE_BINS: tuple[str, ...] = ("00", "01", "05")
ADULT_AGE_BINS: tuple[str, ...] = (
    "10", "15", "20", "25", "30", "35", "40", "45",
    "50", "55", "60", "65", "70", "75", "80", "85", "90",
)
SEXES: tuple[str, ...] = ("m", "f")


@dataclass(frozen=True)
class WorldPopConfig:
    series: str = "Global_2015_2030"
    release: str = "R2025A"
    version: str = "v1"
    resolution: str = "100m"
    constrained: bool = True

    @property
    def type_code(self) -> str:
        return "CN" if self.constrained else "UC"

    @property
    def type_dir(self) -> str:
        return "constrained" if self.constrained else "unconstrained"


def _build_url(country: str, year: int, age: str, sex: str, cfg: WorldPopConfig) -> str:
    """Build the R2025A URL for a per-age, per-sex raster.

    Filename convention: ``{iso_lower}_{sex_lower}_{age}_{year}_CN_100m_R2025A_v1.tif``
    e.g. ``sur_f_00_2020_CN_100m_R2025A_v1.tif`` (Suriname, female, 0-1 yr, 2020).
    """
    iso_upper = country.upper()
    iso_lower = country.lower()
    sex_lower = sex.lower()
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
    with requests.get(url, stream=True, timeout=120) as r:
        if r.status_code == 404:
            return None
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 15):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)
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

    # Shapely geometry (or anything implementing __geo_interface__)
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
        "(xmin, ymin, xmax, ymax)."
    )


def _read_one(
    path: Path, clip_geoms: list[dict] | None
) -> tuple[np.ndarray, dict]:
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
    output_dir: Path | str,
    *,
    clip: Any = None,
    cfg: WorldPopConfig = WorldPopConfig(),
    child_ages: Sequence[str] = CHILD_AGE_BINS,
    adult_ages: Sequence[str] = ADULT_AGE_BINS,
) -> Path:
    """Download age- and sex-disaggregated WorldPop rasters and aggregate them
    into a 3-band GeoTIFF.

    Bands: 1 = children (0-9 yr), 2 = adults (10+ yr), 3 = total.

    The per-age rasters are downloaded into a temporary directory, clipped (if
    a ``clip`` geometry is supplied) and summed in memory; only the final
    combined raster is persisted to ``output_dir``. Each source file is
    deleted right after it's consumed, so peak temp-disk use stays small.

    Parameters
    ----------
    country : str
        ISO3 country code (case-insensitive), e.g. ``"SUR"``.
    year : int
        Year in the 2015-2030 R2025A coverage.
    output_dir : Path | str
        Directory to write the final combined raster.
    clip : optional
        Region of interest. If provided, every per-age raster is masked to
        this geometry before summing, and the final output covers only this
        region. Accepts: ``None`` (no clip; full country), a shapely geometry,
        a GeoJSON dict, a GeoDataFrame/GeoSeries (auto-reprojected to
        EPSG:4326), or a bounds tuple ``(xmin, ymin, xmax, ymax)`` in
        EPSG:4326.
    cfg : WorldPopConfig
        Release / series / resolution / constrained-vs-unconstrained settings.
    child_ages, adult_ages : Sequence[str]
        Age-bin codes that map to the children and adults output bands.

    Returns
    -------
    Path
        Path to the 3-band combined GeoTIFF.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    iso_lower = country.lower()

    clip_geoms = _normalize_clip(clip)
    missing: list[str] = []

    def fetch_group(
        ages: Sequence[str], label: str, tmpdir: Path
    ) -> tuple[np.ndarray, dict]:
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
        return total, profile

    with tempfile.TemporaryDirectory(prefix="d_health_pop_") as td:
        tmpdir = Path(td)
        children, profile = fetch_group(child_ages, "child", tmpdir)
        adults, _ = fetch_group(adult_ages, "adult", tmpdir)

    total = children + adults

    profile.update(driver="GTiff", count=3, dtype="float32", compress="deflate")
    out_path = output_dir / f"{iso_lower}_population_{year}_combined.tif"
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(children.astype(np.float32), 1)
        dst.write(adults.astype(np.float32), 2)
        dst.write(total.astype(np.float32), 3)
        dst.descriptions = ("children_0_9", "adults_10_plus", "total")

    if missing:
        print(
            f"[get_population_data] {len(missing)} of "
            f"{len(child_ages + adult_ages) * len(SEXES)} rasters were missing "
            f"(404). Output bands sum the available ones."
        )

    return out_path
