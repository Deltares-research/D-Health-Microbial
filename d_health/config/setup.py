from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import Field

from d_health.config.base import FrozenModel
from d_health.config.run import ExposureConfig, SettingsConfig


class SetupMetadata(FrozenModel):
    """Provenance metadata captured at setup generation time."""

    country_code: str = Field(
        pattern=r"^[A-Z]{3}$",
        description="ISO3 code used to fetch country-level indicators.",
    )
    country_name: str | None = Field(
        default=None,
        description="Optional human-readable country name from reverse geocoding.",
    )
    aoi_bounds: tuple[float, float, float, float] = Field(
        description="AOI bounds (xmin, ymin, xmax, ymax) in EPSG:4326.",
    )
    country_source: str = Field(
        default="nominatim_reverse_geocode",
        description="How country_code was derived.",
    )


class SetupConfig(FrozenModel):
    """Pre-run setup config.

    This intentionally excludes run-time fields like ``event.flood_depth_map``
    and ``output.out_dir`` so users can produce and reuse exposure data before
    selecting a specific flood map and run destination.
    """

    exposure: ExposureConfig
    settings: SettingsConfig = Field(default_factory=SettingsConfig)
    metadata: SetupMetadata


def load_setup_config(path: str | Path) -> SetupConfig:
    """Load a ``settings.toml`` into a validated ``SetupConfig``.

    Relative paths in ``exposure`` are resolved against the setup file
    directory.
    """
    path = Path(path)
    with path.open("rb") as f:
        user = tomllib.load(f)

    base_dir = path.parent

    def _resolve(p: str) -> str:
        candidate = Path(p)
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()
        return str(candidate)

    exposure = user.get("exposure", {})
    for key in ("population", "urban_rural", "country_indicators"):
        if key in exposure:
            exposure[key] = _resolve(exposure[key])

    return SetupConfig.model_validate(user)
