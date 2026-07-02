from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

import requests
import tomli_w
from pydantic import Field

from d_health.config.base import FrozenModel
from d_health.config.preprocessing import GHSSmodConfig, WDIConfig, WorldPopConfig
from d_health.config.run import ExposureConfig, SettingsConfig
from d_health.config.setup import SetupConfig, SetupMetadata
from d_health.preprocessing import (
    get_country_indicators,
    get_population_data,
    get_smod_data,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ModelSetupOverrides",
    "ModelSetupResult",
    "write_run_config_from_setup",
    "normalize_aoi_bounds",
    "derive_country_from_aoi",
    "model_setup",
]


class ModelSetupOverrides(FrozenModel):
    """Optional overrides for ``model_setup``.

    All defaults intentionally mirror existing preprocessing and model defaults.
    """

    country_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="Optional manual ISO3 override. If set, reverse geocoding is skipped.",
    )
    population_year: int = Field(default=2020, ge=2000, le=2035)
    worldpop: WorldPopConfig = Field(default_factory=WorldPopConfig)
    smod: GHSSmodConfig = Field(default_factory=GHSSmodConfig)
    wdi: WDIConfig = Field(default_factory=WDIConfig)
    settings: SettingsConfig = Field(default_factory=SettingsConfig)
    reverse_geocode_timeout_s: float = Field(default=30.0, gt=0.0)
    reverse_geocode_user_agent: str = Field(default="d_health/0.1")


class ModelSetupResult(FrozenModel):
    """Artifacts produced by ``model_setup``."""

    root_dir: Path
    settings_toml: Path
    population: Path
    urban_rural: Path
    country_indicators: Path
    country_code: str = Field(pattern=r"^[A-Z]{3}$")
    country_name: str | None = None


def _as_bbox_sequence(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (tuple, list)) and len(value) == 4 and all(
        isinstance(v, (int, float)) for v in value
    ):
        return tuple(float(v) for v in value)
    return None


def _merge_bounds(all_bounds: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    if not all_bounds:
        raise ValueError("AOI feature collection is empty.")
    xs1, ys1, xs2, ys2 = zip(*all_bounds)
    return min(xs1), min(ys1), max(xs2), max(ys2)


def _bounds_from_geojson(value: dict) -> tuple[float, float, float, float]:
    kind = value.get("type")
    if kind == "Feature":
        return _bounds_from_geojson_geometry(value["geometry"])
    if kind == "FeatureCollection":
        return _merge_bounds([
            _bounds_from_geojson_geometry(feature["geometry"])
            for feature in value.get("features", [])
        ])
    if "coordinates" in value:
        return _bounds_from_geojson_geometry(value)
    raise TypeError("Unsupported GeoJSON object for AOI.")


def _bounds_from_geojson_geometry(geom: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []

    def _collect(coords: Any) -> None:
        if isinstance(coords, (list, tuple)) and coords:
            if (
                len(coords) >= 2
                and isinstance(coords[0], (int, float))
                and isinstance(coords[1], (int, float))
            ):
                xs.append(float(coords[0]))
                ys.append(float(coords[1]))
                return
            for item in coords:
                _collect(item)

    _collect(geom.get("coordinates", []))
    if not xs or not ys:
        raise ValueError("Could not extract coordinates from AOI geometry.")
    return (min(xs), min(ys), max(xs), max(ys))


def normalize_aoi_bounds(aoi: Any) -> tuple[float, float, float, float]:
    """Return AOI bounds as ``(xmin, ymin, xmax, ymax)`` in EPSG:4326."""
    from_sequence = _as_bbox_sequence(aoi)
    if from_sequence is not None:
        return from_sequence

    if hasattr(aoi, "total_bounds"):
        bounds = getattr(aoi, "total_bounds")
        from_total_bounds = _as_bbox_sequence(bounds)
        if from_total_bounds is not None:
            return from_total_bounds

    if hasattr(aoi, "bounds"):
        bounds = getattr(aoi, "bounds")
        from_bounds = _as_bbox_sequence(bounds)
        if from_bounds is not None:
            return from_bounds

    if hasattr(aoi, "__geo_interface__"):
        return _bounds_from_geojson(aoi.__geo_interface__)

    if isinstance(aoi, dict):
        return _bounds_from_geojson(aoi)

    raise TypeError(
        "Unsupported AOI type. Provide bounds tuple/list, geometry with bounds, "
        "GeoDataFrame/GeoSeries, shapely geometry, or GeoJSON geometry/feature."
    )


def _iso2_to_iso3(iso2: str, *, timeout_s: float) -> str:
    iso2 = iso2.upper()
    url = f"https://api.worldbank.org/v2/country/{iso2}?format=json"
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise ValueError(f"Could not map ISO2={iso2!r} to ISO3 using World Bank API.")
    country = payload[1][0]
    iso3 = str(country.get("id", "")).upper()
    if len(iso3) != 3:
        raise ValueError(f"Invalid ISO3 returned by World Bank API for {iso2!r}: {iso3!r}")
    return iso3


def derive_country_from_aoi(
    aoi: Any,
    *,
    timeout_s: float = 30.0,
    user_agent: str = "d_health/0.1",
) -> tuple[str, str | None, tuple[float, float, float, float]]:
    """Derive ISO3 country code from AOI centroid via online reverse geocoding."""
    xmin, ymin, xmax, ymax = normalize_aoi_bounds(aoi)
    lon = (xmin + xmax) / 2.0
    lat = (ymin + ymax) / 2.0

    url = "https://nominatim.openstreetmap.org/reverse"
    headers = {"User-Agent": user_agent}
    params = {
        "format": "jsonv2",
        "lat": lat,
        "lon": lon,
        "zoom": 3,
        "addressdetails": 1,
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    payload = r.json()
    address = payload.get("address", {}) if isinstance(payload, dict) else {}
    iso2 = str(address.get("country_code", "")).upper()
    country_name = address.get("country")
    if len(iso2) != 2:
        raise ValueError(
            "Reverse geocoding did not return a country_code for AOI centroid. "
            "Provide a manual ISO3 override in ModelSetupOverrides.country_code."
        )
    iso3 = _iso2_to_iso3(iso2, timeout_s=timeout_s)
    return iso3, country_name, (xmin, ymin, xmax, ymax)


def _relpath(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


def _resolve_path(p: Path | str, *, base: Path) -> Path:
    candidate = Path(p)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _for_run_config(path: Path, *, run_dir: Path) -> str:
    try:
        rel = path.relative_to(run_dir)
    except ValueError:
        # Use os.path.relpath semantics while preserving '/' separators.
        rel = Path(os.path.relpath(path, run_dir))
    return str(rel).replace("\\", "/")


def write_run_config_from_setup(
    settings_toml: Path | str,
    flood_depth_map: Path | str,
    run_config_path: Path | str,
    *,
    output_out_dir: Path | str | None = None,
) -> Path:
    """Write a runnable ``config.toml`` from ``settings.toml`` + flood map path.

    ``settings.toml`` is expected to contain ``exposure`` and ``settings``
    sections generated by :func:`model_setup`. If an ``output`` section exists
    (legacy files), it will be honored.
    """
    settings_path = Path(settings_toml)
    run_path = Path(run_config_path)
    run_path.parent.mkdir(parents=True, exist_ok=True)
    settings_base = settings_path.parent.resolve()
    run_base = run_path.parent.resolve()
    cwd_base = Path.cwd().resolve()

    with settings_path.open("rb") as f:
        payload = tomllib.load(f)

    exposure = payload.get("exposure", {})
    exposure_for_run = {
        key: _for_run_config(_resolve_path(val, base=settings_base), run_dir=run_base)
        for key, val in exposure.items()
    }

    flood_abs = _resolve_path(flood_depth_map, base=cwd_base)
    output_payload = payload.get("output", {})
    if output_out_dir is None:
        if "out_dir" in output_payload:
            out_abs = _resolve_path(output_payload["out_dir"], base=settings_base)
        else:
            out_abs = run_base
    else:
        out_abs = _resolve_path(output_out_dir, base=cwd_base)

    run_payload = {
        "exposure": exposure_for_run,
        "event": {"flood_depth_map": _for_run_config(flood_abs, run_dir=run_base)},
        "settings": payload.get("settings", {}),
        "output": {
            **({"plots": True} if "plots" not in output_payload else {}),
            **output_payload,
            "out_dir": _for_run_config(out_abs, run_dir=run_base),
        },
    }
    run_path.write_text(tomli_w.dumps(_drop_none(run_payload)), encoding="utf-8")
    return run_path


def model_setup(
    aoi: Any,
    root_dir: Path | str,
    *,
    overrides: ModelSetupOverrides | None = None,
) -> ModelSetupResult:
    """Build exposure inputs and write a setup ``settings.toml`` for later runs.

    The generated setup file intentionally omits flood map information; users can
    inject ``event.flood_depth_map`` later when creating a run config.
    """
    ov = overrides or ModelSetupOverrides()
    root = Path(root_dir)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if ov.country_code:
        country_code = ov.country_code
        country_name = None
        bounds = normalize_aoi_bounds(aoi)
        country_source = "manual_override"
    else:
        country_code, country_name, bounds = derive_country_from_aoi(
            aoi,
            timeout_s=ov.reverse_geocode_timeout_s,
            user_agent=ov.reverse_geocode_user_agent,
        )
        country_source = "nominatim_reverse_geocode"

    iso_lower = country_code.lower()
    population_path = data_dir / f"{iso_lower}_population_{ov.population_year}_combined.nc"
    urban_rural_path = data_dir / f"{iso_lower}_urban_rural.nc"
    indicators_path = data_dir / f"{iso_lower}_indicators.toml"

    logger.info("Generating exposure inputs for %s into %s", country_code, root)
    get_population_data(
        country_code,
        ov.population_year,
        population_path,
        clip=aoi,
        cfg=ov.worldpop,
    )
    get_smod_data(urban_rural_path, clip=aoi, cfg=ov.smod)
    get_country_indicators(country_code, indicators_path, cfg=ov.wdi)

    setup = SetupConfig(
        exposure=ExposureConfig(
            population=population_path,
            urban_rural=urban_rural_path,
            country_indicators=indicators_path,
        ),
        settings=ov.settings,
        metadata=SetupMetadata(
            country_code=country_code,
            country_name=country_name,
            aoi_bounds=bounds,
            country_source=country_source,
        ),
    )

    settings_toml = root / "settings.toml"
    payload = {
        "exposure": {
            "population": _relpath(setup.exposure.population, root),
            "urban_rural": _relpath(setup.exposure.urban_rural, root),
            "country_indicators": _relpath(setup.exposure.country_indicators, root),
        },
        "settings": setup.settings.model_dump(mode="python"),
        "metadata": _drop_none(setup.metadata.model_dump(mode="python")),
    }
    settings_toml.write_text(tomli_w.dumps(payload), encoding="utf-8")

    return ModelSetupResult(
        root_dir=root.resolve(),
        settings_toml=settings_toml.resolve(),
        population=population_path.resolve(),
        urban_rural=urban_rural_path.resolve(),
        country_indicators=indicators_path.resolve(),
        country_code=country_code,
        country_name=country_name,
    )