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


def test_conc_dry_cells_gate_out(small_meta):
    """Dry cells (depth 0 or NaN) produce non-finite concentration, gating them out."""
    flood = np.array([[0.0, np.nan]], dtype=np.float64)
    emissions = np.array([[1.0e6, 1.0e6]], dtype=np.float64)

    conc = calc_pathogen_conc(small_meta, flood, emissions)

    assert not np.isfinite(conc[0, 0])  # depth 0 -> divide-by-zero -> inf
    assert np.isnan(conc[0, 1])  # depth NaN -> NaN
