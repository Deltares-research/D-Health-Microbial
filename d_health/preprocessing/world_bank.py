from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import wbgapi as wb

from d_health.config.preprocessing import DEFAULT_INDICATOR_CODES, WDIConfig

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS: tuple[str, ...] = (
    "Country Name", "Country Code", "Indicator Name", "Indicator Code",
    "Latest Year", "Latest Value",
)

__all__ = ["WDIConfig", "DEFAULT_INDICATOR_CODES", "fetch_wdi", "get_world_bank_data"]


def _fetch_latest(indicator_codes: tuple[str, ...]) -> pd.DataFrame:
    """Query the World Bank v2 API via wbgapi for the most recent non-empty
    value per (economy, indicator) and return a wide-style long table.

    Uses ``mrnev=1`` so wbgapi returns at most one row per
    ``(economy, indicator)`` — the latest year for which the value isn't
    null. Economies for which an indicator has never been reported are
    simply absent from the result (as if dropped via ``dropna``).
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


def fetch_wdi(cfg: WDIConfig = WDIConfig()) -> pd.DataFrame:
    """Fetch the latest WDI value per ``(economy, indicator)`` as a DataFrame.

    The in-memory counterpart of :func:`get_world_bank_data` (which adds a CSV
    write). Shared by ``get_world_bank_data`` and
    :func:`d_health.preprocessing.country_indicators.get_country_indicators`,
    so the live one-call TOML path and the CSV path read identical data.

    Returns a long table with the columns in ``OUTPUT_COLUMNS`` — one row per
    ``(country, indicator)`` for both real countries and World Bank aggregates.
    Raises ``RuntimeError`` if the API returns nothing.
    """
    logger.info("WDI fetch via wbgapi — %d indicators", len(cfg.indicator_codes))
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
    return df


def get_world_bank_data(
    output_path: Path | str,
    *,
    cfg: WDIConfig = WDIConfig(),
) -> Path:
    """Fetch World Bank Development Indicators via the v2 REST API, keep the
    latest available value per country x indicator, and save a CSV.

    Pipeline: call ``api.worldbank.org/v2`` via the ``wbgapi`` package for the
    requested indicator codes with ``mrnev=1`` (most recent non-empty value
    per economy x indicator), then write a long table to ``output_path``.

    The returned table contains one row per ``(country, indicator)``. Both
    real countries and World Bank regional / income aggregates are included
    (matching the contents of the ``WDICSV.csv`` bulk download).

    To go straight to the model's per-country ``*_indicators.toml`` without an
    intermediate CSV, use
    :func:`d_health.preprocessing.country_indicators.get_country_indicators`.

    Parameters
    ----------
    output_path : Path | str
        Full path of the filtered CSV to write. Parent directories are
        created if they don't exist. If you want to keep per-day snapshots,
        template the date into the path yourself
        (e.g. ``Path(f"data/wdi_{date.today():%Y-%m-%d}.csv")``).
    cfg : WDIConfig
        Indicator codes to fetch and CSV separator.

    Returns
    -------
    Path
        Path to the written CSV (same as ``output_path``).
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = fetch_wdi(cfg)
    df.to_csv(out_path, sep=cfg.csv_sep, index=False)
    logger.info(
        "Wrote %s (%d rows, %.2f MB)",
        out_path.name, len(df), out_path.stat().st_size / 1e6,
    )
    return out_path
