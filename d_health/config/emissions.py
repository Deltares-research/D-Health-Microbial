from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from d_health.config.base import FrozenModel

_SUM_TOLERANCE = 0.5  # percent; allow small rounding error in WB-derived inputs

NodataSanitation = Literal["none", "urban", "rural", "nan"]
"""What sanitation factor to apply to cells the urban/rural raster doesn't classify.

GHS-SMOD leaves cells unclassified (code ``0``) both where it has no data and
where it maps *water* — see ``preprocessing.smod._reclassify``. Those cells still
carry population in the WorldPop raster, so the emissions step has to decide what
sanitation infrastructure to assume for them:

``"none"``
    Factor ``1.0`` — the same value the ``"None"`` sanitation tier gets, i.e.
    *no sanitation infrastructure at all*. This is the maximum-emission
    assumption, applied to the cells we know least about. **The default**, because
    it is what the model has always done; it is a conservative choice, not a
    neutral one.
``"urban"`` / ``"rural"``
    Reuse the country's urban (resp. rural) effective sanitation factor.
``"nan"``
    Exclude the cell from the emissions field entirely.
"""


class SanitationLevel(FrozenModel):
    """One sanitation tier's coverage at country level (percent, 0-100).

    A ``CountryIndicators.sanitation`` list holds one of these per tier
    (typical tiers: ``"Safe"``, ``"Advanced"``, ``"Basic"``, ``"None"``).
    The urban and rural columns are validated to each sum to 100% within a
    0.5 pp tolerance across all tiers.
    """

    name: str = Field(
        description=(
            "Tier name. Must match a ``SanitationReduction.name`` in the "
            "active ``EmissionsConfig.sanitation_reductions`` — the cross-"
            "config name match is enforced by ``RunConfig`` at load time."
        ),
    )
    urban: float = Field(
        ge=0.0,
        le=100.0,
        description="Percent of the urban population in this tier (0-100).",
    )
    rural: float = Field(
        ge=0.0,
        le=100.0,
        description="Percent of the rural population in this tier (0-100).",
    )


class SanitationReduction(FrozenModel):
    """Per-tier multiplier in [0, 1] applied to baseline E. coli emissions.

    The field is named ``reduction_factor`` (the conventional term in this
    domain), but read it as a *retained fraction*, not a removed one:
    ``1.0`` = no sanitation = full baseline emissions retained;
    ``0.10`` = strong sanitation = only 10% of baseline emissions retained.
    Keep this in mind when reading or tuning the numbers — smaller values
    mean *more* sanitation, not less.

    One entry per sanitation tier; the ``name`` must match a tier name in the
    country indicators (``CountryIndicators.sanitation[*].name``).
    """

    name: str = Field(
        description=(
            "Tier name. Must match a ``SanitationLevel.name`` in the active "
            "``CountryIndicators.sanitation``."
        ),
    )
    urban_reduction_factor: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of baseline E. coli emissions retained in urban cells "
            "of this tier (note: retention, not removal — see class "
            "docstring). 1.0 = no sanitation; 0.0 = total removal."
        ),
    )
    rural_reduction_factor: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of baseline E. coli emissions retained in rural cells "
            "of this tier (note: retention, not removal — see class "
            "docstring). 1.0 = no sanitation; 0.0 = total removal."
        ),
    )


class GDPWeight(FrozenModel):
    """Parameters of the linear GDP-based emission weight.

        weight_factor = max(floor, intercept - gdp_per_capita / divisor)

    The weight scales emissions down as GDP per capita rises, using GDP as a
    rough proxy for infrastructure quality: richer countries get a smaller
    weight. GDP per capita is supplied in raw current USD (World Bank
    ``NY.GDP.PCAP.CD``); ``divisor`` sets the USD scale over which the weight
    decays and ``floor`` caps how low it can go. With the defaults below a
    low-income setting such as Mozambique (~657 USD) yields a weight of ~0.99
    (essentially no reduction), while a high-income one approaches the 0.5
    floor.
    """

    floor: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Lower bound of the weight factor (dimensionless, in [0, 1]). "
            "Default 0.5."
        ),
    )
    intercept: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Y-intercept of the linear GDP weight function (dimensionless, "
            "≥ 0). Default 1.0."
        ),
    )
    divisor: float = Field(
        default=80000.0,
        gt=0.0,
        description=(
            "GDP-per-capita divisor (current USD, > 0). Larger values make "
            "the weight decay more slowly with GDP. Default 80000.0 USD."
        ),
    )


def _default_sanitation_reductions() -> list[SanitationReduction]:
    """The default per-tier retained-fraction multipliers.

    One entry per sanitation tier (Safe/Advanced/Basic/None), matching the tier
    names the country indicators use. Semantics are *retention*: 1.0 = no
    sanitation (full emissions retained), smaller = more sanitation.
    """
    return [
        SanitationReduction(
            name="Safe", urban_reduction_factor=0.10, rural_reduction_factor=0.10
        ),
        SanitationReduction(
            name="Advanced", urban_reduction_factor=0.25, rural_reduction_factor=0.25
        ),
        SanitationReduction(
            name="Basic", urban_reduction_factor=0.70, rural_reduction_factor=0.30
        ),
        SanitationReduction(
            name="None", urban_reduction_factor=1.00, rural_reduction_factor=1.00
        ),
    ]


class EmissionsConfig(FrozenModel):
    """Parameters that drive the emissions step (:func:`compute_emissions`).

    These are scenario-/study-level constants shared across the whole run;
    per-country variation lives in ``CountryIndicators`` instead. Every field
    has a sensible default, so ``EmissionsConfig()`` is a complete, ready-to-use
    parameter set.
    """

    per_capita_ecoli_rate: float = Field(
        default=1.0e9,
        gt=0.0,
        description=(
            "Baseline E. coli emission per person per flood event, in CFU "
            "(colony-forming units). Multiplied by sanitation retention and the "
            "GDP weight inside ``compute_emissions``. Default 1.0e9."
        ),
    )
    total_population_group: str = Field(
        default="total",
        description=(
            "Label in the population array's ``group`` dimension holding total "
            "population. Default WorldPop layout uses ``total``. Used by the "
            "pipeline to pick the population-density layer that drives "
            "``compute_emissions``."
        ),
    )
    gdp_weight: GDPWeight = Field(
        default_factory=GDPWeight,
        description=(
            "Parameters of the linear GDP weight factor "
            "``max(floor, intercept - gdp/divisor)``."
        ),
    )
    sanitation_reductions: list[SanitationReduction] = Field(
        default_factory=_default_sanitation_reductions,
        min_length=1,
        description=(
            "Per-tier retained-fraction multipliers (read as retention, not "
            "removal — see ``SanitationReduction``). One entry per sanitation "
            "tier; the tier names must cover every tier in the country "
            "indicators. Defaults to the Safe/Advanced/Basic/None tiers."
        ),
    )
    nodata_sanitation: NodataSanitation = Field(
        default="none",
        description=(
            "Sanitation factor applied where the urban/rural raster is "
            "unclassified (GHS-SMOD code 0: nodata *and* water). Defaults to "
            '``"none"`` (factor 1.0 = no sanitation infrastructure), which '
            "reproduces the model's historical behaviour — a maximum-emission "
            "assumption on the least-known cells. See ``NodataSanitation``."
        ),
    )

    @model_validator(mode="after")
    def _check_unique_names(self) -> EmissionsConfig:
        names = [r.name for r in self.sanitation_reductions]
        if len(set(names)) != len(names):
            raise ValueError(f"sanitation_reductions names must be unique; got {names}")
        return self


class CountryIndicators(FrozenModel):
    """Country-level scalars consumed by ``compute_emissions``.

    Loaded from a standalone TOML file referenced by
    ``ExposureConfig.country_indicators`` — validated at config-load time and
    re-read at run time via ``ExposureConfig.load_country_indicators`` (it is
    not stored as a parsed object on the config).

    The model is agnostic to how the file was produced — the bundled
    ``preprocessing.country_indicators.build_from_wdi`` helper makes one from
    a WDI CSV, but any source that conforms to this schema works.
    """

    country_code: str = Field(
        pattern=r"^[A-Z]{3}$",
        description=(
            'ISO 3166-1 alpha-3 country code, uppercase (e.g. ``"SUR"``). '
            "Used in log lines and downstream output metadata."
        ),
    )
    gdp_per_capita: float = Field(
        ge=0.0,
        description=(
            "Country GDP per capita in current USD. Feeds the GDP weight "
            "formula in ``compute_emissions``; typically WDI indicator "
            "``NY.GDP.PCAP.CD``."
        ),
    )
    sanitation: list[SanitationLevel] = Field(
        min_length=1,
        description=(
            "Per-tier sanitation coverage breakdown. Urban and rural columns "
            "must each sum to 100% (±0.5 pp tolerance for WDI rounding)."
        ),
    )

    @model_validator(mode="after")
    def _check_sums(self) -> CountryIndicators:
        urban_sum = sum(s.urban for s in self.sanitation)
        rural_sum = sum(s.rural for s in self.sanitation)
        if abs(urban_sum - 100.0) > _SUM_TOLERANCE:
            raise ValueError(
                f"sanitation.urban must sum to 100% (within {_SUM_TOLERANCE}); "
                f"got {urban_sum:.3f}"
            )
        if abs(rural_sum - 100.0) > _SUM_TOLERANCE:
            raise ValueError(
                f"sanitation.rural must sum to 100% (within {_SUM_TOLERANCE}); "
                f"got {rural_sum:.3f}"
            )
        names = [s.name for s in self.sanitation]
        if len(set(names)) != len(names):
            raise ValueError(f"sanitation names must be unique; got {names}")
        return self
