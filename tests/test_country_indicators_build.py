"""Test #11: build_from_wdi WB → 4-class derivation."""

from __future__ import annotations

import pandas as pd
import pytest
import tomllib

from d_health.preprocessing.country_indicators import (
    build_from_wdi,
    get_country_indicators,
)


def _synthetic_wdi_df() -> pd.DataFrame:
    rows = []
    # Two countries: SUR (real values), ABC (different values for sanity)
    sur = {
        "NY.GDP.PCAP.CD": 7000.0,
        "SH.STA.SMSS.UR.ZS": 80.0,
        "SH.STA.SMSS.RU.ZS": 50.0,
        "SH.STA.BASS.UR.ZS": 90.0,  # BASS includes SMSS
        "SH.STA.BASS.RU.ZS": 70.0,
        "SH.STA.ODFC.UR.ZS": 5.0,
        "SH.STA.ODFC.RU.ZS": 10.0,
    }
    abc = {
        "NY.GDP.PCAP.CD": 1000.0,
        "SH.STA.SMSS.UR.ZS": 40.0,
        "SH.STA.SMSS.RU.ZS": 20.0,
        "SH.STA.BASS.UR.ZS": 80.0,
        "SH.STA.BASS.RU.ZS": 50.0,
        "SH.STA.ODFC.UR.ZS": 10.0,
        "SH.STA.ODFC.RU.ZS": 30.0,
    }
    for cc, name, data in (("SUR", "Suriname", sur), ("ABC", "Atlantis", abc)):
        for code, val in data.items():
            rows.append(
                {
                    "Country Name": name,
                    "Country Code": cc,
                    "Indicator Name": code,
                    "Indicator Code": code,
                    "Latest Year": 2024,
                    "Latest Value": val,
                }
            )
    return pd.DataFrame(rows)


def _synthetic_wdi(tmp_path):
    path = tmp_path / "wdi.csv"
    _synthetic_wdi_df().to_csv(path, sep=";", index=False)
    return path


def test_build_from_wdi_sur(tmp_path):
    csv = _synthetic_wdi(tmp_path)
    out = build_from_wdi(csv, "SUR", tmp_path / "sur.toml")
    data = tomllib.loads(out.read_text())

    assert data["country_code"] == "SUR"
    assert data["gdp_per_capita"] == 7000.0

    classes = {s["name"]: s for s in data["sanitation"]}
    # Safe = SMSS
    assert classes["Safe"]["urban"] == pytest.approx(80.0)
    assert classes["Safe"]["rural"] == pytest.approx(50.0)
    # Advanced = BASS - SMSS
    assert classes["Advanced"]["urban"] == pytest.approx(90.0 - 80.0)
    assert classes["Advanced"]["rural"] == pytest.approx(70.0 - 50.0)
    # Basic = 100 - BASS - ODFC
    assert classes["Basic"]["urban"] == pytest.approx(100.0 - 90.0 - 5.0)
    assert classes["Basic"]["rural"] == pytest.approx(100.0 - 70.0 - 10.0)
    # None = ODFC
    assert classes["None"]["urban"] == pytest.approx(5.0)
    assert classes["None"]["rural"] == pytest.approx(10.0)

    # Sums to 100 per column
    assert sum(c["urban"] for c in data["sanitation"]) == pytest.approx(100.0)
    assert sum(c["rural"] for c in data["sanitation"]) == pytest.approx(100.0)


def test_build_from_wdi_unknown_country_raises(tmp_path):
    csv = _synthetic_wdi(tmp_path)
    with pytest.raises(KeyError, match="ZZZ"):
        build_from_wdi(csv, "ZZZ", tmp_path / "zzz.toml")


def test_get_country_indicators_one_call(tmp_path, monkeypatch):
    """The one-call live path writes the same TOML as the CSV path (no network)."""
    df = _synthetic_wdi_df()
    monkeypatch.setattr(
        "d_health.preprocessing.country_indicators.fetch_wdi",
        lambda cfg=None: df,
    )

    out = get_country_indicators("SUR", tmp_path / "sur_indicators.toml")
    assert out.name == "sur_indicators.toml"

    data = tomllib.loads(out.read_text())
    assert data["country_code"] == "SUR"
    assert data["gdp_per_capita"] == 7000.0
    classes = {s["name"]: s for s in data["sanitation"]}
    assert classes["Safe"]["urban"] == pytest.approx(80.0)
    assert classes["Advanced"]["urban"] == pytest.approx(90.0 - 80.0)
    assert classes["None"]["rural"] == pytest.approx(10.0)
    assert sum(c["urban"] for c in data["sanitation"]) == pytest.approx(100.0)
    assert sum(c["rural"] for c in data["sanitation"]) == pytest.approx(100.0)
