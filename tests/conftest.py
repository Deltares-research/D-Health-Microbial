"""Synthetic fixtures so tests never touch real rasters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from rasterio.coords import BoundingBox
from rasterio.crs import CRS
from rasterio.transform import from_origin

from d_health.io import from_numpy
from d_health.config.emissions import (
    CountryIndicators,
    EmissionsConfig,
    GDPWeight,
    SanitationLevel,
    SanitationReduction,
)
from d_health.config.groups import DepthThreshold, PopulationGroup
from d_health.config.pathogen import PathogenConfig, PathogenParameters


def _write_country_toml(path: Path, country: CountryIndicators) -> Path:
    """Serialise a ``CountryIndicators`` to a TOML file at ``path``.

    Country indicators are now read from disk at run time (there is no
    ``model.country`` object), so tests that build a config or run the pipeline
    need a real TOML for ``exposure.country_indicators`` to point at.
    """
    lines = [
        f'country_code = "{country.country_code}"',
        f"gdp_per_capita = {country.gdp_per_capita}",
    ]
    for s in country.sanitation:
        lines += [
            "[[sanitation]]",
            f'name = "{s.name}"',
            f"urban = {s.urban}",
            f"rural = {s.rural}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def write_country_toml():
    """Return a helper that dumps a ``CountryIndicators`` to a TOML file."""
    return _write_country_toml


@pytest.fixture
def small_meta() -> dict:
    """16x16 grid with a real UTM CRS so geo.get_cell_area returns a real m²."""
    transform = from_origin(west=200000.0, north=600000.0, xsize=100.0, ysize=100.0)
    # SUR is UTM 21N (EPSG:32621); arbitrary choice for a test fixture.
    crs = CRS.from_epsg(32621)
    # BoundingBox is a namedtuple — supports both *unpacking and .left attribute access.
    bounds = BoundingBox(left=200000.0, bottom=598400.0, right=201600.0, top=600000.0)
    return {
        "transform": transform,
        "crs": crs,
        "bounds": bounds,
        "width": 16,
        "height": 16,
        "count": 1,
    }


@pytest.fixture
def flood_16x16() -> np.ndarray:
    """A 16x16 flood raster spanning depths 0, 0.05, 0.3, 1.0, 2.0 m
    (positive = flooded, 0 = dry)."""
    arr = np.zeros((16, 16), dtype=np.float32)
    arr[:4, :] = 0.0  # dry
    arr[4:8, :] = 0.05  # below adults' wading threshold
    arr[8:12, :] = 0.3  # adults wading, children wading
    arr[12:14, :] = 1.0  # adults wading, children swimming
    arr[14:, :] = 2.0  # adults swimming, children swimming
    return arr


@pytest.fixture
def population_16x16(small_meta) -> xr.DataArray:
    """Population DataArray with a labelled ``group`` dim: children/adults/total."""
    children = np.full((16, 16), 10.0, dtype=np.float32)
    adults = np.full((16, 16), 30.0, dtype=np.float32)
    total = children + adults
    data = np.stack([children, adults, total], axis=0)
    return from_numpy(
        data,
        small_meta["transform"],
        small_meta["crs"],
        name="population",
        group=("children", "adults", "total"),
    )


@pytest.fixture
def urban_rural_16x16() -> np.ndarray:
    """Half urban (1), half rural (2), with a stripe of nodata (0)."""
    arr = np.zeros((16, 16), dtype=np.int8)
    arr[:, :7] = 1  # urban
    arr[:, 7] = 0  # nodata stripe
    arr[:, 8:] = 2  # rural
    return arr


@pytest.fixture
def default_groups() -> list[PopulationGroup]:
    """The default adults/children population groups (matches SettingsConfig defaults)."""
    return [
        PopulationGroup(
            name="adults",
            depth_thresholds=[
                DepthThreshold(name="wading", min_depth=0.1, ing=10.0, unit="ml/h"),
                DepthThreshold(name="swimming", min_depth=1.5, ing=30.0, unit="ml/h"),
            ],
        ),
        PopulationGroup(
            name="children",
            depth_thresholds=[
                DepthThreshold(name="wading", min_depth=0.1, ing=30.0, unit="ml/h"),
                DepthThreshold(name="swimming", min_depth=0.5, ing=50.0, unit="ml/h"),
            ],
        ),
    ]


@pytest.fixture
def default_pathogen() -> PathogenConfig:
    return PathogenConfig(
        selected="E.coli",
        pathogens={
            "E.coli": PathogenParameters(
                alpha=0.373,
                beta=39.71,
                source="Teunis et al. (2008)",
            ),
        },
    )


@pytest.fixture
def default_emissions_cfg() -> EmissionsConfig:
    return EmissionsConfig(
        per_capita_ecoli_rate=1.0e9,
        total_population_group="total",
        gdp_weight=GDPWeight(),
        sanitation_reductions=[
            SanitationReduction(
                name="Safe", urban_reduction_factor=0.10, rural_reduction_factor=0.10
            ),
            SanitationReduction(
                name="Advanced",
                urban_reduction_factor=0.25,
                rural_reduction_factor=0.25,
            ),
            SanitationReduction(
                name="Basic", urban_reduction_factor=0.70, rural_reduction_factor=0.30
            ),
            SanitationReduction(
                name="None", urban_reduction_factor=1.00, rural_reduction_factor=1.00
            ),
        ],
    )


@pytest.fixture
def default_country() -> CountryIndicators:
    """Synthetic SUR-like indicators: percentages sum to 100 per column."""
    return CountryIndicators(
        country_code="SUR",
        gdp_per_capita=7000.0,
        sanitation=[
            SanitationLevel(name="Safe", urban=80.0, rural=50.0),
            SanitationLevel(name="Advanced", urban=10.0, rural=20.0),
            SanitationLevel(name="Basic", urban=5.0, rural=20.0),
            SanitationLevel(name="None", urban=5.0, rural=10.0),
        ],
    )
