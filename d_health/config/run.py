from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import Field, model_validator

from d_health.config.base import FrozenModel
from d_health.config.emissions import CountryIndicators, EmissionsConfig
from d_health.config.groups import DepthThreshold, PopulationGroup
from d_health.config.pathogen import PathogenConfig


def _default_population_groups() -> list[PopulationGroup]:
    """The bundled adults/children groups, as default objects.

    The default groups are adults and children, each with a wading and a
    swimming depth band. A group's ``name`` both labels the outputs
    and selects the matching layer from the population array's ``group`` dim.
    """
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


class ExposureConfig(FrozenModel):
    """The region's static, non-forcing inputs the model reads at run time.

    These describe *what the flood acts on*: where people are, whether cells are
    urban or rural, and the country-level indicators. All three are file paths.
    Paths may be absolute or relative; relative paths in a config.toml are resolved
    against the config.toml's directory at load time by ``load_run_config`` (so a
    config.toml is self-contained and portable regardless of the working directory
    it's invoked from). Absolute paths are used as-is.
    """

    population: Path = Field(
        description=(
            "netCDF of population per cell with a labelled ``group`` "
            "dimension. Default bundled layout: ``children`` (0-9), "
            "``adults`` (10+), ``total`` — see "
            "``PopulationGroup.name`` and "
            "``EmissionsConfig.total_population_group``. A multi-band GeoTIFF "
            "is also accepted (bands mapped to groups positionally)."
        ),
    )
    urban_rural: Path = Field(
        description=(
            "netCDF (or GeoTIFF) of urban/rural classification, GHS-SMOD "
            "convention: ``1`` = urban, ``2`` = rural, ``0`` = nodata. "
            "Resampled nearest-neighbour to the flood grid."
        ),
    )
    country_indicators: Path = Field(
        description=(
            "Standalone TOML matching the ``CountryIndicators`` schema (GDP per "
            "capita + per-tier sanitation breakdown). Validated at config-load "
            "time and re-read at run time by ``load_country_indicators`` to feed "
            "``compute_emissions`` — it is not stored as a parsed object on the "
            "config. Relative paths are resolved against the config.toml's "
            "directory."
        ),
    )

    def load_country_indicators(self) -> CountryIndicators:
        """Read and validate the ``country_indicators`` TOML into a ``CountryIndicators``.

        Called both by the load-time validator (to fail fast on a missing or
        malformed file) and by the pipeline at run time (to obtain the country
        scalars for ``compute_emissions``).
        """
        with Path(self.country_indicators).open("rb") as f:
            data = tomllib.load(f)
        return CountryIndicators.model_validate(data)

    @model_validator(mode="after")
    def _validate_country_indicators_file(self) -> "ExposureConfig":
        # Fail fast: parse + validate the country indicators TOML now, rather
        # than deep inside the pipeline. Paths have already been resolved to
        # absolute by load_run_config before this validator runs.
        self.load_country_indicators()
        return self


class EventConfig(FrozenModel):
    """The forcing: the flood map that drives the run.

    A single-layer raster path. Relative paths in a config.toml are resolved
    against the config.toml's directory by ``load_run_config``.
    """

    flood_depth_map: Path = Field(
        description=(
            "netCDF (or GeoTIFF) of flood depth in metres, *positive for "
            "flooded cells* (``0`` or nodata = dry). Single layer; "
            "CRS/resolution determine the grid every other raster is sampled "
            "to."
        ),
    )


class OutputConfig(FrozenModel):
    """Where the pipeline writes its rasters and (optional) plots, plus run options."""

    out_dir: Path = Field(
        description=(
            "Directory for output rasters (emissions, pathogen_conc, "
            "dose_*, risk_*, infected_*) and PNG plots. Created if missing."
        ),
    )
    plots: bool = Field(
        default=True,
        description=(
            "If true, write PNG plots alongside each output raster "
            "(``emissions.png`` plus per-group dose/risk/infected panels)."
        ),
    )


class SettingsConfig(FrozenModel):
    """General, non-country-specific parameters of the model run.

    Every field has a built-in default, so the whole ``[settings]`` table is
    optional in a config.toml — declare a section only to override its default.

    Country-specific scalars are *not* here — they come from the
    ``ExposureConfig.country_indicators`` TOML, read at run time.
    """

    pathogen: PathogenConfig = Field(
        default_factory=PathogenConfig,
        description=(
            "Pathogen catalogue and the one selected for this run. Defaults to "
            "the bundled ``E.coli`` entry."
        ),
    )
    population_groups: list[PopulationGroup] = Field(
        default_factory=_default_population_groups,
        min_length=1,
        description=(
            "Population groups whose dose, risk, and infected counts are "
            "computed independently. Defaults to the bundled adults/children "
            "groups. Declaring ``[[settings.population_groups]]`` in a "
            "config.toml replaces the default list wholesale."
        ),
    )
    emissions: EmissionsConfig = Field(
        default_factory=EmissionsConfig,
        description=(
            "Literature parameters for the emissions step. Defaults to the "
            "bundled emissions constants and sanitation tiers."
        ),
    )
    event_in_hours: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Duration of a single flood-exposure event in hours. Used to "
            "normalise population-group ingestion rates expressed in "
            "``ml/event`` (``ing / event_in_hours`` → mL/h). Has no effect on "
            "rates already given in ``ml/h``. Default 1.0."
        ),
    )


class RunConfig(FrozenModel):
    """Top-level run configuration: exposure, event, settings, output.

    Built by ``load_run_config`` from a single user config.toml. Model
    parameters default to bundled Python objects (see ``SettingsConfig``); the
    country indicators referenced by ``exposure.country_indicators`` are
    validated at load time and re-read at run time.
    """

    exposure: ExposureConfig = Field(
        description="Static, non-forcing inputs: population, urban/rural, country.",
    )
    event: EventConfig = Field(description="The forcing: the flood map.")
    settings: SettingsConfig = Field(
        default_factory=SettingsConfig,
        description="General (non-country-specific) model parameters.",
    )
    output: OutputConfig = Field(description="Where the pipeline writes results.")

    @model_validator(mode="after")
    def _check_sanitation_name_coverage(self) -> "RunConfig":
        country = self.exposure.load_country_indicators()
        country_names = {s.name for s in country.sanitation}
        reduction_names = {
            r.name for r in self.settings.emissions.sanitation_reductions
        }
        missing = country_names - reduction_names
        if missing:
            raise ValueError(
                f"country_indicators has sanitation tier(s) {sorted(missing)} "
                f"with no matching settings.emissions.sanitation_reductions "
                f"entry. Each country sanitation tier must have a "
                f"reduction-factor entry."
            )
        return self
