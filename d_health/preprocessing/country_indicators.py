"""Build a ``country_indicators.toml`` for the model from a WDI CSV.

The WDI CSV is the output of :func:`d_health.preprocessing.world_bank.get_world_bank_data`.
For a given ISO3 country code, this helper extracts the required indicators and
maps the World Bank's WASH indicators onto the four sanitation tiers the model
uses (Safe / Advanced / Basic / None), per urban and rural. Those four tiers
are the categories the emissions step assigns a retained-fraction multiplier to
(see :class:`d_health.config.emissions.SanitationReduction`).

WB → 4-tier mapping (urban; rural is analogous):
    Safe     = SH.STA.SMSS.UR.ZS
    Advanced = SH.STA.BASS.UR.ZS - SH.STA.SMSS.UR.ZS    # BASS includes SMSS
    Basic    = 100 - SH.STA.BASS.UR.ZS - SH.STA.ODFC.UR.ZS
    None     = SH.STA.ODFC.UR.ZS

Running ``build_from_wdi`` writes a ``country_indicators.toml`` that
``ExposureConfig.country_indicators`` can point at.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from d_health.config.preprocessing import WDIConfig
from d_health.preprocessing.world_bank import fetch_wdi

logger = logging.getLogger(__name__)

# WDI indicator codes needed by the emissions calculation.
_GDP_CODE = "NY.GDP.PCAP.CD"
_WASH_CODES = {
    "smss_urban": "SH.STA.SMSS.UR.ZS",  # Safely managed sanitation, urban
    "smss_rural": "SH.STA.SMSS.RU.ZS",
    "bass_urban": "SH.STA.BASS.UR.ZS",  # Basic sanitation (incl. safely managed), urban
    "bass_rural": "SH.STA.BASS.RU.ZS",
    "odfc_urban": "SH.STA.ODFC.UR.ZS",  # Open defecation, urban
    "odfc_rural": "SH.STA.ODFC.RU.ZS",
}


def _get(df: pd.DataFrame, country_code: str, indicator_code: str) -> float:
    rows = df[
        (df["Country Code"] == country_code) & (df["Indicator Code"] == indicator_code)
    ]
    if rows.empty:
        raise KeyError(
            f"WDI CSV is missing {indicator_code!r} for country {country_code!r}"
        )
    val = rows.iloc[0]["Latest Value"]
    if pd.isna(val):
        raise ValueError(
            f"WDI CSV has null value for {indicator_code!r} / {country_code!r}"
        )
    return float(val)


def _format_toml(country_code: str, gdp: float, classes: list[dict]) -> str:
    """Render the indicators dict to a TOML string by hand (no extra deps)."""
    lines: list[str] = []
    lines.append(f'country_code   = "{country_code}"')
    lines.append(f"gdp_per_capita = {gdp}")
    lines.append("")
    lines.append(
        "# WB-derived 4-class sanitation breakdown (percent, sums to 100 per column)."
    )
    for c in classes:
        lines.append("[[sanitation]]")
        lines.append(f'name  = "{c["name"]}"')
        lines.append(f'urban = {c["urban"]:.4f}')
        lines.append(f'rural = {c["rural"]:.4f}')
    return "\n".join(lines) + "\n"


def _derive_indicators(df: pd.DataFrame, country_code: str) -> tuple[float, list[dict]]:
    """GDP + the WB→4-class WASH breakdown for one country, from a WDI long table.

    Shared by :func:`build_from_wdi` (CSV) and :func:`get_country_indicators`
    (live fetch) so both produce identical numbers.
    """
    gdp = _get(df, country_code, _GDP_CODE)
    smss_u = _get(df, country_code, _WASH_CODES["smss_urban"])
    smss_r = _get(df, country_code, _WASH_CODES["smss_rural"])
    bass_u = _get(df, country_code, _WASH_CODES["bass_urban"])
    bass_r = _get(df, country_code, _WASH_CODES["bass_rural"])
    odfc_u = _get(df, country_code, _WASH_CODES["odfc_urban"])
    odfc_r = _get(df, country_code, _WASH_CODES["odfc_rural"])

    # WB → 4-tier mapping (see module docstring):
    safe_u, safe_r = smss_u, smss_r
    adv_u, adv_r = bass_u - smss_u, bass_r - smss_r  # BASS includes SMSS
    basic_u, basic_r = 100.0 - bass_u - odfc_u, 100.0 - bass_r - odfc_r
    none_u, none_r = odfc_u, odfc_r

    classes = [
        {"name": "Safe", "urban": safe_u, "rural": safe_r},
        {"name": "Advanced", "urban": adv_u, "rural": adv_r},
        {"name": "Basic", "urban": basic_u, "rural": basic_r},
        {"name": "None", "urban": none_u, "rural": none_r},
    ]
    return gdp, classes


def _write_indicators(
    country_code: str, gdp: float, classes: list[dict], out_path: str | Path
) -> Path:
    """Render and write the indicators TOML; log a one-line summary."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_format_toml(country_code, gdp, classes), encoding="utf-8")

    by = {c["name"]: c for c in classes}
    logger.info(
        "Wrote %s (GDP=%.0f, Safe u/r=%.1f/%.1f, None u/r=%.1f/%.1f)",
        out_path,
        gdp,
        by["Safe"]["urban"],
        by["Safe"]["rural"],
        by["None"]["urban"],
        by["None"]["rural"],
    )
    return out_path


def get_country_indicators(
    country_code: str,
    output_path: str | Path,
    *,
    cfg: WDIConfig = WDIConfig(),
) -> Path:
    """Fetch WDI for one country and write its model ``*_indicators.toml`` — in
    one call.

    The single-step counterpart to ``get_world_bank_data`` + ``build_from_wdi``:
    pulls the latest WDI values via :func:`d_health.preprocessing.world_bank.fetch_wdi`,
    derives the 4-class WASH breakdown (Safe / Advanced / Basic / None, per urban
    and rural) plus GDP per capita, and writes a TOML matching
    ``d_health.config.emissions.CountryIndicators``. Mirrors
    :func:`d_health.preprocessing.population.get_population_data` and
    :func:`d_health.preprocessing.smod.get_smod_data` — give it a country and an
    output path, get the model input back.

    Parameters
    ----------
    country_code : str
        ISO3 country code (e.g. ``"SUR"``).
    output_path : Path | str
        Destination TOML path. By convention name it
        ``f"{country_code.lower()}_indicators.toml"``. Parent dirs are created.
    cfg : WDIConfig
        Indicator codes to fetch (defaults cover GDP + the WASH triplets the
        derivation needs).

    Returns
    -------
    Path
        ``output_path``.
    """
    df = fetch_wdi(cfg)
    gdp, classes = _derive_indicators(df, country_code)
    return _write_indicators(country_code, gdp, classes, output_path)


def build_from_wdi(
    wdi_csv: str | Path,
    country_code: str,
    out_path: str | Path,
    *,
    sep: str = ";",
) -> Path:
    """Read a WDI CSV, derive the 4-class WASH breakdown for one country, and
    write a ``country_indicators.toml`` consumable by the model.

    The CSV-based building block behind :func:`get_country_indicators` — use
    this when you already have a WDI CSV from ``get_world_bank_data`` (e.g. to
    inspect it first, or to derive several countries offline from one pull).

    Parameters
    ----------
    wdi_csv : Path | str
        Output CSV from ``get_world_bank_data``.
    country_code : str
        ISO3 country code (e.g. ``"SUR"``).
    out_path : Path | str
        Destination TOML path.
    sep : str
        CSV separator. Defaults to the ``;`` used by ``get_world_bank_data``.

    Returns
    -------
    Path
        ``out_path``.
    """
    df = pd.read_csv(Path(wdi_csv), sep=sep)
    gdp, classes = _derive_indicators(df, country_code)
    return _write_indicators(country_code, gdp, classes, out_path)
