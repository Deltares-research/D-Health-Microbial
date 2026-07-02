from __future__ import annotations

from typing import Literal

from pydantic import Field

from d_health.config.base import FrozenModel

# WorldPop --------------------------------------------------------------------

WorldPopLayout = Literal["global1_2000_2020", "global2_2015_2030"]
"""Selects which WorldPop product family / URL layout to fetch.

``"global1_2000_2020"``
    The ``Global_2000_2020(_Constrained)`` series (hub aliases
    ``ascic_2020`` / ``aswpgp``). Flat URL ``{series}/{year}/{ISO}/`` and
    filenames ``{iso}_{sex}_{age}_{year}_constrained.tif`` (or without the
    suffix for the unconstrained variant). **Unpadded** single-digit age
    codes (``"0"``, ``"1"``, ``"5"``) and adults capped at age 80. This is the
    **default** here.

``"global2_2015_2030"``
    The newer ``Global_2015_2030`` "Global 2" series (R2025A and later).
    Nested URL ``{series}/{release}/{year}/{ISO}/{version}/{resolution}/
    {type_dir}/`` and filenames ``{iso}_{sex}_{age}_{year}_{type_code}_
    {resolution}_{release}_{version}.tif``. **Zero-padded** age codes
    (``"00"``, ``"01"``, ``"05"``) and adults extended to age 90."""

CHILD_AGE_BINS_LEGACY: tuple[str, ...] = ("0", "1", "5")
"""``global1_2000_2020`` children codes (ages 0-9): ``"0"`` = 0, ``"1"`` =
1-4, ``"5"`` = 5-9. Unpadded, matching that product's filenames."""

CHILD_AGE_BINS_G2: tuple[str, ...] = ("00", "01", "05")
"""``global2_2015_2030`` children codes (ages 0-9), zero-padded."""

ADULT_AGE_BINS_LEGACY: tuple[str, ...] = (
    "10",
    "15",
    "20",
    "25",
    "30",
    "35",
    "40",
    "45",
    "50",
    "55",
    "60",
    "65",
    "70",
    "75",
    "80",
)
"""``global1_2000_2020`` adult codes (ages 10+): 5-year cohorts top-coded at
80 (the product has no 85/90 cohorts)."""

ADULT_AGE_BINS_G2: tuple[str, ...] = (
    "10",
    "15",
    "20",
    "25",
    "30",
    "35",
    "40",
    "45",
    "50",
    "55",
    "60",
    "65",
    "70",
    "75",
    "80",
    "85",
    "90",
)
"""``global2_2015_2030`` adult codes (ages 10+): 5-year cohorts top-coded at
90."""

# Backwards-compatible aliases pointing at the current default product
# (``global1_2000_2020``). ``get_population_data`` resolves the correct bins
# from the active ``WorldPopConfig`` so these never desync with the layout.
CHILD_AGE_BINS: tuple[str, ...] = CHILD_AGE_BINS_LEGACY
ADULT_AGE_BINS: tuple[str, ...] = ADULT_AGE_BINS_LEGACY


class WorldPopConfig(FrozenModel):
    """Selects a WorldPop age/sex-disaggregated population raster.

    The **default** fetches the constrained ``Global_2000_2020_Constrained``
    100 m product (hub alias ``ascic_2020``, DOI 10.5258/SOTON/WP00696). Set
    ``layout="global2_2015_2030"`` to fetch the newer 2025 "Global 2" R2025A
    re-estimate instead.

    Estimate vs projection
    ----------------------
    The ``Global_2015_2030`` R2025A release (``layout="global2_2015_2030"``,
    hub alias ``G2_CN_Age_R25A_100m``, the "Global 2" / Global Demographic
    Data Project, DOI 10.5258/SOTON/WP00841) is a **single 2025 modelling run
    that outputs a continuous yearly series 2015-2030**. The release directory
    holds year folders ``2015/`` … ``2030/``. The post-base years (≈2025-2030 —
    beyond the present) are genuine **forward projections**. Years inside the
    estimation range (e.g. ``year=2020``) are **2025-vintage re-estimates /
    hindcasts**, not projections — but they are *not* identical to a same-year
    raster from the older release because they use newer census inputs, updated
    UN World Population Prospects national totals and a newer building-footprint
    settlement layer.

    Difference between the two layouts
    ----------------------------------
    The default ``global1_2000_2020`` layout (hub alias ``ascic_2020``,
    DOI 10.5258/SOTON/WP00696, built 2020) uses filenames
    ``{iso}_{sex}_{age}_{year}_constrained.tif`` with **unpadded** single-digit
    age codes (e.g. ``"0"``, ``"1"``, ``"5"``) and caps adults at age 80. The
    ``global2_2015_2030`` layout uses the 2025-vintage ``R2025A v1`` release,
    **zero-padded** age codes (``"00"``, ``"01"``, ``"05"``) and extends adults
    to age 90. The two products are not bit-for-bit comparable: per-cell
    population values can differ even for the same country and year (for
    Beira/Mozambique 2020 the R2025A product places ~1.5× more people on the
    identical grid and a younger age structure). For a retrospective event
    analysis the older, contemporaneous product is usually the more defensible
    primary input, with R2025A run as a sensitivity case.
    """

    layout: WorldPopLayout = Field(
        default="global1_2000_2020",
        description=(
            'WorldPop product family / URL layout. ``"global1_2000_2020"`` '
            "(default) is the constrained 2020 product; "
            "``\"global2_2015_2030\"`` is the newer R2025A 'Global 2' "
            "re-estimate. Drives the URL structure, filename convention, "
            "age-code padding and adult age cap."
        ),
    )
    constrained: bool = Field(
        default=True,
        description=(
            "If true, use the *constrained* WorldPop variant (population "
            "restricted to settled areas from a building-footprint settlement "
            "layer). If false, use the unconstrained dasymetric variant. For "
            "``global1_2000_2020`` this selects the ``Global_2000_2020_"
            "Constrained`` vs ``Global_2000_2020`` series and the "
            "``_constrained`` filename suffix; for ``global2_2015_2030`` it "
            'drives ``type_code`` (``"CN"``/``"UC"``) and ``type_dir``.'
        ),
    )
    release: str = Field(
        default="R2025A",
        description=(
            "Release tag for the ``global2_2015_2030`` layout (e.g. "
            '``"R2025A"``). Ignored by ``global1_2000_2020``.'
        ),
    )
    version: str = Field(
        default="v1",
        description=(
            "Sub-version for the ``global2_2015_2030`` layout (e.g. "
            '``"v1"``). Ignored by ``global1_2000_2020``.'
        ),
    )
    resolution: Literal["100m", "1km"] = Field(
        default="100m",
        description=(
            "Spatial resolution for the ``global2_2015_2030`` layout. The "
            "``global1_2000_2020`` constrained product is 100 m only."
        ),
    )

    @property
    def series(self) -> str:
        """Top-level WorldPop series folder, derived from layout + constrained."""
        if self.layout == "global1_2000_2020":
            return (
                "Global_2000_2020_Constrained"
                if self.constrained
                else "Global_2000_2020"
            )
        return "Global_2015_2030"

    @property
    def type_code(self) -> str:
        return "CN" if self.constrained else "UC"

    @property
    def type_dir(self) -> str:
        return "constrained" if self.constrained else "unconstrained"

    @property
    def child_age_bins(self) -> tuple[str, ...]:
        """Children age codes (ages 0-9) matching this layout's padding."""
        return (
            CHILD_AGE_BINS_LEGACY
            if self.layout == "global1_2000_2020"
            else CHILD_AGE_BINS_G2
        )

    @property
    def adult_age_bins(self) -> tuple[str, ...]:
        """Adult age codes (ages 10+) matching this layout's cap (80 vs 90)."""
        return (
            ADULT_AGE_BINS_LEGACY
            if self.layout == "global1_2000_2020"
            else ADULT_AGE_BINS_G2
        )


# GHS-SMOD --------------------------------------------------------------------


class GHSSmodConfig(FrozenModel):
    """Selects a GHS-SMOD product variant on the JRC open-data server.

    Defaults reproduce ``GHS_SMOD_E2025_GLOBE_R2023A_4326_30ss_V2_0.tif`` —
    the 2025 epoch, R2023A release, 30 arc-second (~1 km) global raster in
    EPSG:4326.
    """

    epoch: int = Field(
        default=2025,
        ge=1975,
        le=2030,
        description=(
            "GHS-SMOD temporal epoch (year). JRC publishes 5-year steps from "
            "1975 to 2030."
        ),
    )
    release: str = Field(
        default="R2023A",
        description=(
            'JRC release tag (e.g. ``"R2023A"``). Free string because JRC '
            "adds new releases over time."
        ),
    )
    version: str = Field(
        default="V2-0",
        description=(
            "JRC product version. Note the JRC inconsistency: the URL path "
            'uses ``"V2-0"`` while the filename uses ``"V2_0"`` — the '
            "``version_filename`` property handles the substitution."
        ),
    )
    crs_code: int = Field(
        default=4326,
        description=(
            "EPSG code of the source raster. JRC publishes the global 30 "
            "arc-second product in EPSG:4326 (geographic) and the 1 km / "
            "100 m products in EPSG:54009 (Mollweide)."
        ),
    )
    resolution: str = Field(
        default="30ss",
        description=(
            'JRC resolution token. Known values: ``"30ss"`` (30 arc-'
            'seconds, EPSG:4326), ``"1000"`` (1 km, EPSG:54009), '
            '``"100"`` (100 m, EPSG:54009).'
        ),
    )

    @property
    def version_filename(self) -> str:
        # JRC convention: "V2-0" in the URL path, "V2_0" in the filename.
        return self.version.replace("-", "_")

    @property
    def stem(self) -> str:
        return (
            f"GHS_SMOD_E{self.epoch}_GLOBE_{self.release}"
            f"_{self.crs_code}_{self.resolution}"
        )

    @property
    def zip_url(self) -> str:
        return (
            f"https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
            f"GHS_SMOD_GLOBE_{self.release}/"
            f"{self.stem}/{self.version}/{self.stem}_{self.version_filename}.zip"
        )

    @property
    def tif_name(self) -> str:
        return f"{self.stem}_{self.version_filename}.tif"


# World Bank WDI --------------------------------------------------------------

DEFAULT_INDICATOR_CODES: tuple[str, ...] = (
    "NY.GDP.PCAP.CD",
    "SH.STA.ODFC.ZS",
    "SH.STA.ODFC.RU.ZS",
    "SH.STA.ODFC.UR.ZS",
    "SH.STA.BASS.ZS",
    "SH.STA.BASS.RU.ZS",
    "SH.STA.BASS.UR.ZS",
    "SH.STA.SMSS.ZS",
    "SH.STA.SMSS.RU.ZS",
    "SH.STA.SMSS.UR.ZS",
)
"""WDI indicator codes the default ``WDIConfig`` fetches: GDP per capita
(current USD) plus the open-defecation / basic-sanitation / safely-managed-
sanitation national / rural / urban triplets used to derive the country-level
sanitation breakdown in ``preprocessing.country_indicators.build_from_wdi``."""


class WDIConfig(FrozenModel):
    """Selects which WDI indicators to keep and the output CSV separator."""

    indicator_codes: tuple[str, ...] = Field(
        default=DEFAULT_INDICATOR_CODES,
        description=(
            'Indicator codes (e.g. ``"NY.GDP.PCAP.CD"``) to fetch via '
            "``wbgapi``. Each code becomes one row per economy in the output "
            "CSV."
        ),
    )
    csv_sep: Literal[",", ";", "\t"] = Field(
        default=";",
        description=(
            "Separator for the output CSV. Restricted to comma, semicolon "
            "or tab — values flow into pandas' ``DataFrame.to_csv``."
        ),
    )
