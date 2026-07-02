"""Smoke tests for the rioxarray-based align_rasters."""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

from d_health.geo import align_rasters
from d_health.io import from_numpy


def _da(values, west, north, xres, yres, *, epsg=32621, name="r", group=None):
    transform = from_origin(west=west, north=north, xsize=xres, ysize=yres)
    return from_numpy(values, transform, CRS.from_epsg(epsg), name=name, group=group)


def test_align_identical_grid_is_noop_shape():
    """When input and target share a grid, output shape matches and values pass through."""
    src_vals = np.arange(16 * 16, dtype=np.float32).reshape(16, 16)
    src = _da(src_vals, 0.0, 1600.0, 100.0, 100.0, name="src")
    tgt = _da(
        np.zeros((16, 16), dtype=np.float32), 0.0, 1600.0, 100.0, 100.0, name="tgt"
    )

    aligned, clipped = align_rasters(src, tgt, resampling="nearest")

    assert aligned.shape == (16, 16)
    assert clipped.shape == (16, 16)
    # nearest resampling on identical grids preserves values exactly
    assert np.allclose(aligned.values, src_vals, equal_nan=True)


def test_align_input_smaller_than_target_clips_target():
    """Smaller input → target is clipped to the overlap; both outputs share a grid."""
    tgt = _da(
        np.full((32, 32), 7.0, dtype=np.float32), 0.0, 3200.0, 100.0, 100.0, name="tgt"
    )
    src = _da(
        np.full((8, 8), 3.0, dtype=np.float32), 800.0, 2400.0, 100.0, 100.0, name="src"
    )

    aligned, clipped = align_rasters(src, tgt, resampling="nearest")

    assert aligned.shape == clipped.shape == (8, 8)
    assert np.all(clipped.values == 7.0)
    assert np.allclose(aligned.values, 3.0, equal_nan=True)


def test_align_no_overlap_raises():
    tgt = _da(
        np.zeros((16, 16), dtype=np.float32), 0.0, 1600.0, 100.0, 100.0, name="tgt"
    )
    src = _da(
        np.zeros((4, 4), dtype=np.float32),
        1_000_000.0,
        2_000_000.0,
        100.0,
        100.0,
        name="src",
    )
    with pytest.raises(ValueError, match="do not overlap"):
        align_rasters(src, tgt)


def test_align_bad_resampling_raises():
    tgt = _da(np.zeros((4, 4), dtype=np.float32), 0.0, 400.0, 100.0, 100.0, name="tgt")
    src = _da(np.zeros((4, 4), dtype=np.float32), 0.0, 400.0, 100.0, 100.0, name="src")
    with pytest.raises(ValueError, match="Unknown resampling"):
        align_rasters(src, tgt, resampling="not_a_method")


def test_align_target_group_dim_preserved():
    """A multi-group target keeps its group dim (and labels) through clipping."""
    vals = np.stack(
        [
            np.full((32, 32), 1.0, dtype=np.float32),
            np.full((32, 32), 2.0, dtype=np.float32),
            np.full((32, 32), 3.0, dtype=np.float32),
        ]
    )
    tgt = _da(
        vals,
        0.0,
        3200.0,
        100.0,
        100.0,
        name="population",
        group=("children", "adults", "total"),
    )
    src = _da(
        np.full((8, 8), 5.0, dtype=np.float32),
        800.0,
        2400.0,
        100.0,
        100.0,
        name="flood",
    )

    aligned, clipped = align_rasters(src, tgt, resampling="nearest")

    assert aligned.shape == (8, 8)
    assert "group" in clipped.dims
    assert clipped.sizes["group"] == 3
    assert list(map(str, clipped["group"].values)) == ["children", "adults", "total"]
    assert np.allclose(clipped.sel(group="total").values, 3.0, equal_nan=True)
