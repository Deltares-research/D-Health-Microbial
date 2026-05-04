# Download World Bank data
# Filter to just relevant information (latest year, GDP + sanitation)
# Save

from pathlib import Path
from zipfile import ZipFile
import requests
import pandas as pd
from datetime import datetime

WDI_CSV_URL = "https://databank.worldbank.org/data/download/WDI_CSV.zip"


def download_wdi_csv(out_dir=Path("wdi_data"), read_main_csv=True):
    zip_path = out_dir / "WDI_CSV.zip"

    print("Downloading WDI CSV zip...")
    with requests.get(WDI_CSV_URL, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    print("Extracting...")
    with ZipFile(zip_path, "r") as z:
        z.extractall(out_dir)

    print(f"Extracted files to: {out_dir.resolve()}")

    if read_main_csv:
        data_path = out_dir / "WDICSV.csv"
        print("Reading WDICSV.csv...")
        df = pd.read_csv(data_path)
        return df

    return None

def filter_wdi_latest(df, indicator_codes):
    """
    Filter WDI dataframe to selected indicator codes and return the latest
    available value per country x indicator (with year).

    Parameters
    ----------
    df : pandas.DataFrame
    indicator_codes : list[str]

    Returns
    -------
    pandas.DataFrame
        One row per country x indicator with latest year + value
    """

    df = df.copy()
    df.columns = df.columns.str.strip()

    id_cols = [
        "Country Name",
        "Country Code",
        "Indicator Name",
        "Indicator Code",
    ]

    # --- Filter by indicator codes ---
    df = df[df["Indicator Code"].isin(indicator_codes)]

    # --- Reshape to long ---
    df_long = df.melt(
        id_vars=id_cols,
        var_name="Year",
        value_name="Value",
    )

    df_long["Year"] = pd.to_numeric(df_long["Year"], errors="coerce")
    df_long["Value"] = pd.to_numeric(df_long["Value"], errors="coerce")

    # Remove invalid rows
    df_long = df_long.dropna(subset=["Year", "Value"])
    df_long["Year"] = df_long["Year"].astype(int)

    # --- Keep latest per country x indicator ---
    df_latest = (
        df_long
        .sort_values("Year")
        .groupby(id_cols, as_index=False)
        .tail(1)
        .reset_index(drop=True)
        .rename(columns={
            "Year": "Latest Year",
            "Value": "Latest Value",
        })
    )

    # Sort
    df_latest = df_latest.sort_values(["Country Code", "Indicator Code"]).reset_index(drop=True)

    return df_latest

codes = [
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
]

def main():
    out_dir=Path("wdi_data")
    out_dir.mkdir(parents=True, exist_ok=True)
    df = download_wdi_csv(out_dir)
    if df is None:
        raise RuntimeError("Failed to load WDI data")
    df_filtered = filter_wdi_latest(df, codes)
    today_str = datetime.today().strftime("%Y-%m-%d")
    filepath =  out_dir / f"wdi_{today_str}.csv"
    df_filtered.to_csv(filepath, sep=";", index=False)
    print(f"Loaded data shape: {df.shape}")
    print(f"Filtered data shape: {df_filtered.shape}")
    print(f"Saved to {filepath}")

if __name__ == "__main__":
    main()
    
