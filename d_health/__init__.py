import logging as _logging
import sys as _sys

from d_health.config import (
    RunConfig,
    load_run_config,
)
from d_health.geo import align_rasters
from d_health.model import (
    ModelOutputs,
    ModelSetupOverrides,
    ModelSetupResult,
    derive_country_from_aoi,
    model_setup,
    run_model,
    run_model_from_toml,
    write_run_config_from_setup,
)
from d_health.preprocessing import (
    GHSSmodConfig,
    WDIConfig,
    WorldPopConfig,
    build_from_wdi,
    get_country_indicators,
    get_population_data,
    get_smod_data,
    get_world_bank_data,
)

__version__ = "0.1.0"

__all__ = [
    # preprocessing
    "WorldPopConfig",
    "get_population_data",
    "GHSSmodConfig",
    "get_smod_data",
    "WDIConfig",
    "get_world_bank_data",
    "align_rasters",
    "build_from_wdi",
    "get_country_indicators",
    # model
    "RunConfig",
    "ModelOutputs",
    "ModelSetupOverrides",
    "ModelSetupResult",
    "load_run_config",
    "derive_country_from_aoi",
    "model_setup",
    "write_run_config_from_setup",
    "run_model",
    "run_model_from_toml",
    "__version__",
]


def _configure_default_logging() -> None:
    """Attach a stderr handler at INFO level to the `d_health` logger if the
    user hasn't configured one already. Sets ``propagate=False`` so messages
    don't also bubble up to the root logger and get duplicated or filtered.
    """
    logger = _logging.getLogger("d_health")
    if logger.handlers:
        return  # user (or a previous import) already configured it
    handler = _logging.StreamHandler(_sys.stderr)
    handler.setFormatter(_logging.Formatter("%(name)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(_logging.INFO)
    logger.propagate = False


_configure_default_logging()
