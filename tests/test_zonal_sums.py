"""Zonal aggregation of model rasters onto polygons.

The grid under test is the shared ``small_meta`` fixture: 16x16 cells of 100 m,
origin (200000, 600000) in EPSG:32621, so the northern half of the grid is
y in [599200, 600000] and the southern half y in [598400, 599200].
"""

from __future__ import annotations

import numpy as np
import pytest

from d_health.postprocessing import zonal_sums


def _box(west: float, south: float, east: float, north: float) -> dict:
    """A GeoJSON-like polygon, in whatever CRS the caller's grid uses."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                (west, south),
                (east, south),
                (east, north),
                (west, north),
                (west, south),
            ]
        ],
    }


NORTH_HALF = _box(200000.0, 599200.0, 201600.0, 600000.0)
SOUTH_HALF = _box(200000.0, 598400.0, 201600.0, 599200.0)
OFF_GRID = _box(300000.0, 598400.0, 301600.0, 600000.0)


def test_splits_totals_between_zones(small_meta):
    people = np.ones((16, 16), dtype=np.float32)
    infected = np.zeros((16, 16), dtype=np.float32)
    infected[:8, :] = 2.0  # only the northern half has infections

    totals = zonal_sums(
        {"people": people, "infected": infected},
        small_meta,
        [(NORTH_HALF, 0), (SOUTH_HALF, 1)],
    )

    assert totals == {
        0: {"people": 128.0, "infected": 256.0},
        1: {"people": 128.0, "infected": 0.0},
    }


def test_nan_cells_do_not_poison_the_total(small_meta):
    # The pipeline writes NaN, not 0, on unexposed cells.
    infected = np.full((16, 16), np.nan, dtype=np.float32)
    infected[0, :4] = 1.0

    totals = zonal_sums({"infected": infected}, small_meta, [(NORTH_HALF, 0)])

    assert totals[0]["infected"] == 4.0


def test_zone_outside_the_grid_totals_zero(small_meta, caplog):
    people = np.ones((16, 16), dtype=np.float32)

    with caplog.at_level("WARNING"):
        totals = zonal_sums(
            {"people": people}, small_meta, [(NORTH_HALF, 0), (OFF_GRID, 7)]
        )

    assert totals[7]["people"] == 0.0
    assert "cover no grid cell" in caplog.text


def test_overlapping_zones_do_not_double_count(small_meta):
    people = np.ones((16, 16), dtype=np.float32)
    overlap = _box(200000.0, 599200.0, 200800.0, 600000.0)  # west half of the north

    totals = zonal_sums({"people": people}, small_meta, [(NORTH_HALF, 0), (overlap, 1)])

    # Later shapes win where polygons overlap, so the 64 shared cells belong to
    # zone 1 only and the two zones still sum to the northern half's 128.
    assert totals[1]["people"] == 64.0
    assert totals[0]["people"] == 64.0


def test_no_shapes_returns_empty(small_meta):
    people = np.ones((16, 16), dtype=np.float32)

    assert zonal_sums({"people": people}, small_meta, []) == {}


def test_array_not_matching_the_grid_raises(small_meta):
    with pytest.raises(ValueError, match="expected"):
        zonal_sums(
            {"people": np.ones((8, 8), dtype=np.float32)},
            small_meta,
            [(NORTH_HALF, 0)],
        )


def test_negative_zone_id_raises(small_meta):
    with pytest.raises(ValueError, match="must be >= 0"):
        zonal_sums(
            {"people": np.ones((16, 16), dtype=np.float32)},
            small_meta,
            [(NORTH_HALF, -1)],
        )
