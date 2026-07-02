"""Test #1: dose-threshold semantics per group."""

from __future__ import annotations

import numpy as np

from d_health.model.exposure import calc_dose_per_group


def test_dose_thresholds_adults(default_groups):
    adults = default_groups[0]
    # Concentration = 100 CFU per 100 mL → dose per h = ing * 100 / 100 = ing.
    conc = np.full((1, 5), 100.0)
    abs_depth = np.array([[0.0, 0.05, 0.1, 1.0, 2.0]])
    dose = calc_dose_per_group(abs_depth, conc, adults)
    # depth < 0.1 → NaN (no exposure)
    assert np.isnan(dose[0, 0])
    assert np.isnan(dose[0, 1])
    # 0.1 <= depth < 1.5 → wading (10 mL/h)
    assert np.isclose(dose[0, 2], 10.0)
    assert np.isclose(dose[0, 3], 10.0)
    # depth >= 1.5 → swimming (30 mL/h)
    assert np.isclose(dose[0, 4], 30.0)


def test_dose_thresholds_children(default_groups):
    children = default_groups[1]
    conc = np.full((1, 5), 100.0)
    abs_depth = np.array([[0.0, 0.05, 0.1, 0.6, 2.0]])
    dose = calc_dose_per_group(abs_depth, conc, children)
    assert np.isnan(dose[0, 0])
    assert np.isnan(dose[0, 1])
    # 0.1 <= depth < 0.5 → wading (30 mL/h)
    assert np.isclose(dose[0, 2], 30.0)
    # depth >= 0.5 → swimming (50 mL/h)
    assert np.isclose(dose[0, 3], 50.0)
    assert np.isclose(dose[0, 4], 50.0)
