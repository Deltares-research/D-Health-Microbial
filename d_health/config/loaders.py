from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from d_health.config.run import RunConfig

logger = logging.getLogger(__name__)


def load_run_config(path: str | Path) -> RunConfig:
    """Load a config.toml into a validated ``RunConfig``.

    Model parameters (pathogen, emissions, population groups, ``event_in_hours``)
    default to bundled Python objects, so a config.toml only needs the
    ``[exposure]``, ``[event]`` and ``[output]`` sections plus any
    ``[settings]`` overrides.

    All paths (``exposure.population``, ``exposure.urban_rural``,
    ``exposure.country_indicators``, ``event.flood_depth_map``,
    ``output.out_dir``) may be absolute or relative; relative paths are resolved
    against the config.toml's directory so a config.toml is self-contained and
    portable regardless of the working directory it's invoked from.

    Validation (including the country-indicators TOML structure check and the
    sanitation-tier-name coverage check) fires during ``RunConfig.model_validate``.
    """
    path = Path(path)
    logger.info("Loading run config from %s", path)

    with path.open("rb") as f:
        user = tomllib.load(f)

    # Resolve every input path relative to the config.toml's directory so a
    # config.toml is self-contained and portable regardless of the working
    # directory it's invoked from. Absolute paths are left untouched.
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

    event = user.get("event", {})
    if "flood_depth_map" in event:
        event["flood_depth_map"] = _resolve(event["flood_depth_map"])

    output = user.get("output", {})
    if "out_dir" in output:
        output["out_dir"] = _resolve(output["out_dir"])

    return RunConfig.model_validate(user)
