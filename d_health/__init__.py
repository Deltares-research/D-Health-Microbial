import logging as _logging
import sys as _sys

from d_health.get_population_data import (
    WorldPopConfig,
    get_population_data,
)
from d_health.get_smod_data import (
    GHSSmodConfig,
    get_smod_data,
)
from d_health.utils import align_flood_and_population

__version__ = "0.1.0"

__all__ = [
    "WorldPopConfig",
    "get_population_data",
    "GHSSmodConfig",
    "get_smod_data",
    "align_flood_and_population",
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
    handler.setFormatter(
        _logging.Formatter("%(name)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(_logging.INFO)
    logger.propagate = False


_configure_default_logging()
