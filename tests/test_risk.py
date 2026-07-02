"""Test #2: beta-Poisson risk is monotonic and bounded."""

from __future__ import annotations

import numpy as np

from d_health.model.risk import calc_infection_risk_beta_poisson

# Bundled E.coli parameters (Teunis et al. 2008).
ALPHA = 0.373
BETA = 39.71


def test_beta_poisson_monotonic_and_bounded():
    doses = np.linspace(0, 1e3, 50)
    risks = calc_infection_risk_beta_poisson(doses, alpha=ALPHA, beta=BETA)

    assert np.all(risks >= 0.0)
    assert np.all(risks < 1.0)
    assert risks[0] == 0.0  # dose=0 -> risk=0
    # strictly increasing
    assert np.all(np.diff(risks) > 0)


def test_beta_poisson_nan_propagates():
    dose = np.array([np.nan, 100.0, np.nan])
    risk = calc_infection_risk_beta_poisson(dose, alpha=ALPHA, beta=BETA)
    assert np.isnan(risk[0])
    assert np.isfinite(risk[1])
    assert np.isnan(risk[2])
