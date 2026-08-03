from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from rasterio.features import rasterize

logger = logging.getLogger(__name__)

# Cells covered by no zone. Zone ids are therefore required to be >= 0.
_NO_ZONE = -1


def per_group_totals(infected: dict[str, np.ndarray]) -> dict[str, float]:
    """Sum each group's infected raster, NaN-safe.

    Returns one total per population group, keyed ``f"infected_{group}"``
    (e.g. ``"infected_adults"``) — the totals the CLI prints and the pipeline
    reports.
    """
    return {f"infected_{name}": float(np.nansum(arr)) for name, arr in infected.items()}


def zonal_sums(
    arrays: Mapping[str, np.ndarray],
    meta: Mapping[str, Any],
    shapes: Sequence[tuple[Any, int]],
    *,
    all_touched: bool = False,
) -> dict[int, dict[str, float]]:
    """Sum model rasters over polygons, NaN-safe.

    Every array is summed per zone with ``np.nansum``, so the NaN the pipeline
    writes on unexposed cells reads as "nothing here" rather than poisoning the
    zone total.

    Parameters
    ----------
    arrays
        Quantity name -> 2-D array on the common grid described by ``meta``.
        Extensive quantities only (people, infections): summing an intensive
        one such as risk gives a number without meaning — divide two sums
        instead.
    meta
        Georeferencing dict of that grid (``transform`` / ``width`` /
        ``height``), as returned by :func:`d_health.io.da_to_meta` and carried
        on ``ModelOutputs.meta``.
    shapes
        ``(geometry, zone_id)`` pairs in rasterio's convention, where geometry
        is a GeoJSON-like mapping **in the CRS of** ``meta`` and ``zone_id`` is
        a non-negative int. Later shapes win where polygons overlap.
    all_touched
        Burn every cell the polygon touches instead of only those whose centre
        it covers. Off by default, which keeps neighbouring zones from both
        claiming a boundary cell and double-counting its people.

    Returns
    -------
    dict
        ``{zone_id: {quantity_name: total}}``, one entry per distinct id in
        ``shapes``. Zones that cover no cell get 0.0 for every quantity.
    """
    height, width = int(meta["height"]), int(meta["width"])
    for name, arr in arrays.items():
        if arr.shape != (height, width):
            raise ValueError(
                f"array '{name}' has shape {arr.shape}, expected "
                f"{(height, width)} from meta"
            )

    if not shapes:
        return {}

    zone_ids = sorted({int(zone_id) for _, zone_id in shapes})
    if zone_ids[0] < 0:
        raise ValueError(f"zone ids must be >= 0, got {zone_ids[0]}")

    zones = rasterize(
        shapes,
        out_shape=(height, width),
        transform=meta["transform"],
        fill=_NO_ZONE,
        all_touched=all_touched,
        dtype="int32",
    )

    totals: dict[int, dict[str, float]] = {}
    empty: list[int] = []
    for zone_id in zone_ids:
        mask = zones == zone_id
        if not mask.any():
            empty.append(zone_id)
        totals[zone_id] = {
            name: float(np.nansum(arr[mask])) for name, arr in arrays.items()
        }

    if empty:
        logger.warning(
            "%d of %d zones cover no grid cell and total 0: %s",
            len(empty),
            len(zone_ids),
            empty,
        )
    return totals
