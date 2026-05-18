from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import wbgapi as wb

logger = logging.getLogger(__name__)

# GDP per capita + WASH (open-defecation / basic-sanitation / safely-managed-sanitation,
# total + rural + urban breakdowns).
DEFAULT_INDICATOR_CODES: tuple[str, ...] = (
    "NY.GDP.PCAP.CD",
    "SH.STA.ODFC.ZS", "SH.STA.ODFC.RU.ZS", "SH.STA.ODFC.UR.ZS",
    "SH.STA.BASS.ZS", "SH.STA.BASS.RU.ZS", "SH.STA.BASS.UR.ZS",
    "SH.STA.SMSS.ZS", "SH.STA.SMSS.RU.ZS", "SH.STA.SMSS.UR.ZS",
)

OUTPUT_COLUMNS: tuple[str, ...] = (
    "Country Name", "Country Code", "Indicator Name", "Indicator Code",
    "Latest Year", "Latest Value",
)


@dataclass(frozen=True)
class WDIConfig:
    """Selects which WDI indicators to keep and the output CSV separator."""

    indicator_codes: tuple[str, ...] = DEFAULT_INDICATOR_CODES
    csv_sep: str = ";"


def _fetch_latest(indicator_codes: tuple[str, ...]) -> pd.DataFrame:
    """Query the World Bank v2 API via wbgapi for the most recent non-empty
    value per (economy, indicator) and return a wide-style long table.

    Uses ``mrnev=1`` so wbgapi returns at most one row per
    ``(economy, indicator)`` — the latest year for which the value isn't
    null. Economies for which an indicator has never been reported are
    simply absent (matching the old behaviour of ``dropna``).
    """
    rows: list[dict[str, object]] = []
    for r in wb.data.fetch(list(indicator_codes), mrnev=1, labels=True):
        # Row shape (labels=True):
        #   {'value': float,
        #    'series':  {'id': 'NY.GDP.PCAP.CD', 'value': 'GDP per capita ...'},
        #    'economy': {'id': 'SUR', 'value': 'Suriname', 'aggregate': False},
        #    'time':    {'id': 'YR2024', 'value': '2024'}}
        rows.append({
            "Country Name":   r["economy"]["value"],
            "Country Code":   r["economy"]["id"],
            "Indicator Name": r["series"]["value"],
            "Indicator Code": r["series"]["id"],
            "Latest Year":    int(r["time"]["value"]),
            "Latest Value":   r["value"],
        })
    df = pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS))
    return (
        df.sort_values(["Country Code", "Indicator Code"])
        .reset_index(drop=True)
    )


def get_world_bank_data(
    output_dir: Path | str,
    *,
    cfg: WDIConfig = WDIConfig(),
) -> Path:
    """Fetch World Bank Development Indicators via the v2 REST API, keep the
    latest available value per country x indicator, and save a CSV.

    Pipeline: call ``api.worldbank.org/v2`` via the ``wbgapi`` package for the
    requested indicator codes with ``mrnev=1`` (most recent non-empty value
    per economy x indicator), then write a long table to
    ``output_dir / wdi_<YYYY-MM-DD>.csv``.

    The returned table contains one row per ``(country, indicator)``. Both
    real countries and World Bank regional / income aggregates are included
    (matching the contents of the ``WDICSV.csv`` bulk download).

    Parameters
    ----------
    output_dir : Path | str
        Directory the filtered CSV is written into.
    cfg : WDIConfig
        Indicator codes to fetch and CSV separator.

    Returns
    -------
    Path
        Path to ``wdi_<YYYY-MM-DD>.csv`` in ``output_dir``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "WDI fetch via wbgapi — %d indicators", len(cfg.indicator_codes),
    )
    df = _fetch_latest(cfg.indicator_codes)
    if df.empty:
        raise RuntimeError(
            f"World Bank API returned no rows for indicators "
            f"{cfg.indicator_codes!r}. Check the indicator codes."
        )
    logger.info(
        "Received %d rows across %d economies x %d indicators",
        len(df), df["Country Code"].nunique(), df["Indicator Code"].nunique(),
    )

    today_str = datetime.today().strftime("%Y-%m-%d")
    out_path = output_dir / f"wdi_{today_str}.csv"
    df.to_csv(out_path, sep=cfg.csv_sep, index=False)
    logger.info(
        "Wrote %s (%d rows, %.2f MB)",
        out_path.name, len(df), out_path.stat().st_size / 1e6,
    )
    return out_path
