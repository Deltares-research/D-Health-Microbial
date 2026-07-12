"""Golden numbers: a tripwire under the physics.

Every other test in this suite checks *shapes*, *keys*, *bounds* and
*non-negativity*. None of them checks a value, so every constant in the model
could shift by 20% and the suite would stay green. For a tool whose entire output
is a number someone will put in a report, that is the gap that matters.

These tests are **not** a claim that the numbers are right. They are frozen
observations of what the model currently produces on the standard 16x16
fixtures. If one fails, the question is not "what did I break" but:

    the physics changed — was that on purpose?

A diff cannot answer that on its own. If the change was intentional, update the
constants below in the same commit that changed the model, and say why in the
message. If it wasn't, you just caught a regression that would otherwise have
shipped.

Values captured 2026-07-12 against the fixtures in conftest.py, on the commit
that introduced the dry-cell gate (results verified byte-identical to the
pre-fix model for a valid config).
"""

from __future__ import annotations

import numpy as np
import pytest

from d_health.config.run import (
    EventConfig,
    ExposureConfig,
    OutputConfig,
    RunConfig,
    SettingsConfig,
)
from d_health.model.inputs import ModelInputs
from d_health.model.pipeline import run_model
from d_health.model.risk import calc_infection_risk_beta_poisson

# Frozen end-to-end results on the conftest fixtures.
GOLDEN_TOTALS = {
    "infected_adults": 547.0617999498314,
    "infected_children": 358.0284667066124,
}
GOLDEN_EMISSIONS_SUM = 2.575440e12
GOLDEN_DOSE_SUMS = {"adults": 2951.025, "children": 8853.075}
GOLDEN_RISK_SUMS = {"adults": 18.235393331661047, "children": 35.80284667066124}
# 0 = dry, 1 = wet below any threshold, 2..4 = the activity bands.
GOLDEN_FLOOD_CLASS_COUNTS = {0: 64, 1: 64, 2: 64, 3: 32, 4: 32}
GOLDEN_FLOODED_POPULATION = {"total": 7680.0, "adults": 5760.0, "children": 1920.0}


@pytest.fixture
def golden_run(
    tmp_path,
    small_meta,
    flood_16x16,
    population_16x16,
    urban_rural_16x16,
    default_pathogen,
    default_groups,
    default_emissions_cfg,
    default_country,
    write_country_toml,
):
    ind = write_country_toml(tmp_path / "ind.toml", default_country)
    config = RunConfig(
        exposure=ExposureConfig(
            population=tmp_path / "pop.tif",
            urban_rural=tmp_path / "ur.tif",
            country_indicators=ind,
        ),
        event=EventConfig(flood_depth_map=tmp_path / "flood.tif"),
        output=OutputConfig(out_dir=tmp_path / "out", plots=False),
        settings=SettingsConfig(
            pathogen=default_pathogen,
            population_groups=default_groups,
            emissions=default_emissions_cfg,
        ),
    )
    inputs = ModelInputs(
        flood=flood_16x16,
        flood_meta=small_meta,
        population=population_16x16,
        urban_rural=urban_rural_16x16,
    )
    return run_model(config, inputs=inputs)


def test_golden_totals(golden_run):
    """The headline numbers — what the CLI prints and a report quotes."""
    assert golden_run.totals == pytest.approx(GOLDEN_TOTALS, rel=1e-9)


def test_golden_intermediate_fields(golden_run):
    """Pin each step, so a failure localises instead of just going red."""
    assert float(np.nansum(golden_run.emissions)) == pytest.approx(
        GOLDEN_EMISSIONS_SUM, rel=1e-9
    )
    for group, expected in GOLDEN_DOSE_SUMS.items():
        assert float(np.nansum(golden_run.doses[group])) == pytest.approx(
            expected, rel=1e-9
        ), f"dose sum drifted for {group}"
    for group, expected in GOLDEN_RISK_SUMS.items():
        assert float(np.nansum(golden_run.risks[group])) == pytest.approx(
            expected, rel=1e-9
        ), f"risk sum drifted for {group}"


def test_golden_no_infinities_anywhere(golden_run):
    """An inf risk is silently a risk of 1.0. Nothing may be infinite."""
    for name, arr in (
        ("emissions", golden_run.emissions),
        ("pathogen_conc", golden_run.pathogen_conc),
        *((f"dose_{k}", v) for k, v in golden_run.doses.items()),
        *((f"risk_{k}", v) for k, v in golden_run.risks.items()),
        *((f"infected_{k}", v) for k, v in golden_run.infected.items()),
    ):
        assert not np.isinf(arr).any(), f"{name} contains inf"


def test_golden_flood_classes(golden_run):
    classes, counts = np.unique(golden_run.flood_classes, return_counts=True)
    assert dict(zip(classes.tolist(), counts.tolist(), strict=True)) == (
        GOLDEN_FLOOD_CLASS_COUNTS
    )


def test_golden_coverage(golden_run):
    assert golden_run.coverage.flooded == pytest.approx(
        GOLDEN_FLOODED_POPULATION, rel=1e-9
    )


@pytest.mark.parametrize(
    "dose, expected_risk",
    [
        # Beta-Poisson with the bundled E. coli parameters (Teunis et al. 2008,
        # alpha=0.373, beta=39.71): risk = 1 - (1 + dose/beta)^-alpha.
        (0.0, 0.0),
        # dose == beta -> 1 - 2^-0.373; check by hand: 2^-0.373 = 0.772175,
        # so risk = 0.227825.
        (39.71, 0.22782486690821502),
        # 1 + 1000/39.71 = 26.183; 26.183^-0.373 = 0.295857 -> risk = 0.704143.
        (1000.0, 0.7041433063917724),
    ],
)
def test_golden_beta_poisson_kernel(dose, expected_risk):
    """The dose-response curve itself, at hand-checkable points.

    If the end-to-end goldens move but this holds, the kernel is fine and
    something upstream (emissions, concentration, ingestion) changed.
    """
    risk = calc_infection_risk_beta_poisson(np.array([dose]), 0.373, 39.71)
    assert float(risk[0]) == pytest.approx(expected_risk, rel=1e-12)
