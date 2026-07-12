"""Concentration: flood depth is positive (>0 flooded, 0/NaN dry)."""

from __future__ import annotations

import numpy as np

from d_health.geo import get_cell_area
from d_health.model.concentration import M3_TO_HL, calc_pathogen_conc


def test_conc_positive_depth(small_meta):
    """Positive flood depth yields positive concentration = E / (area·depth·factor)."""
    flood = np.array([[1.0, 2.0]], dtype=np.float64)  # metres, flooded
    emissions = np.array([[1.0e6, 1.0e6]], dtype=np.float64)

    conc = calc_pathogen_conc(small_meta, flood, emissions)

    area = get_cell_area(small_meta)
    expected = emissions / (area * flood * M3_TO_HL)
    assert np.all(conc > 0)
    assert np.allclose(conc, expected)


def test_conc_dry_cells_are_nan_not_inf(small_meta):
    """Dry cells (depth 0, negative, or NaN) yield NaN — never inf.

    Regression: dividing by a depth of 0 gives +inf, and an inf concentration
    becomes an inf dose and a *risk of 1.0* — dry land reporting certain
    infection. The gate must be explicit, not an artifact of which min_depth the
    population groups happen to use.
    """
    flood = np.array([[0.0, np.nan, -1.0]], dtype=np.float64)
    emissions = np.array([[1.0e6, 1.0e6, 1.0e6]], dtype=np.float64)

    conc = calc_pathogen_conc(small_meta, flood, emissions)

    assert np.isnan(conc).all()
    assert not np.isinf(conc).any()
