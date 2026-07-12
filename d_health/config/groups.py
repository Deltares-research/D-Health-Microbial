from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from d_health.config.base import FrozenModel


class DepthThreshold(FrozenModel):
    """One depth band in a ``PopulationGroup``'s ingestion table.

    Bands are flood-depth-ordered: the threshold at index ``i`` applies for
    absolute flood depth (meters, positive) in ``[min_depth_i, min_depth_{i+1})``,
    with ``min_depth_{n+1}`` = +∞ for the last entry. Cells below
    ``depth_thresholds[0].min_depth`` get NaN dose: the water is too shallow for
    this group to ingest any floodwater, so they are treated as unexposed.

    The ``name`` (e.g. ``"wading"``, ``"swimming"``) is a human-readable label
    describing how the group experiences the flood at this depth — children
    start "swimming" at a shallower depth than adults. It is used only for
    readability and flood-class labelling, not by the model maths.

    Ingestion can be expressed either per hour (``"ml/h"``, used directly) or
    per event (``"ml/event"``, normalised by the run-level ``event_in_hours``);
    both flow through ``ingestion_ml_per_h``.
    """

    name: str = Field(
        description=(
            'Label for this depth band (e.g. ``"wading"``, ``"swimming"``) '
            "describing how the group experiences the flood at this depth. "
            "Used for readability and flood-class labelling; must be unique "
            "within a group."
        ),
    )
    min_depth: float = Field(
        ge=0.0,
        description=(
            "Lower bound of this band's depth range, in metres of absolute "
            "flood depth (positive). The band extends to the next threshold's "
            "``min_depth`` (or +∞ for the last entry). Thresholds are required "
            "to be sorted ascending by this value."
        ),
    )
    ing: float = Field(
        ge=0.0,
        description=(
            "Ingestion of floodwater within this band, in the units given by "
            "``unit`` (mL/h or mL/event)."
        ),
    )
    unit: Literal["ml/h", "ml/event"] = Field(
        description=(
            'Unit of ``ing``. ``"ml/h"`` is used as-is; ``"ml/event"`` is '
            "divided by the run-level ``SettingsConfig.event_in_hours`` inside "
            "``ingestion_ml_per_h`` to yield mL/h."
        ),
    )

    def ingestion_ml_per_h(self, event_in_hours: float) -> float:
        """Normalise this band's ingestion to mL/h using the run's ``event_in_hours``."""
        if self.unit == "ml/h":
            return self.ing
        # "ml/event"
        return self.ing / event_in_hours


class PopulationGroup(FrozenModel):
    """One population group (e.g. adults, children) with a depth-banded ingestion table.

    ``name`` does double duty: it labels the group throughout the pipeline
    outputs (``dose_<name>``, ``risk_<name>``, ``infected_<name>``) *and*
    selects this group's headcount layer from the population array's ``group``
    dimension via ``population.sel(group=name)``. Its ``depth_thresholds`` table
    describes which ingestion rate applies at each flood depth.
    """

    name: str = Field(
        description=(
            "Group name. Used as the dict key throughout the pipeline outputs "
            "(``dose_<name>``, ``risk_<name>``, ``infected_<name>``) and as the "
            "label selected from the population array's ``group`` dimension "
            "(``population.sel(group=name)``). Default bundled layout: "
            "``children`` (0-9), ``adults`` (10+). Must be unique across the "
            "run's groups."
        ),
    )
    depth_thresholds: list[DepthThreshold] = Field(
        min_length=1,
        description=(
            "Depth-banded ingestion table sorted ascending by "
            "``DepthThreshold.min_depth``. Validated at load time. See "
            "``DepthThreshold`` for the depth-banding semantics."
        ),
    )

    @model_validator(mode="after")
    def _check_depth_thresholds(self) -> PopulationGroup:
        depths = [t.min_depth for t in self.depth_thresholds]
        if depths != sorted(depths):
            raise ValueError(
                f"group {self.name!r}: depth_thresholds must be sorted ascending "
                f"by min_depth; got {depths}"
            )
        # A group cannot be exposed at zero depth: a dry cell holds no
        # floodwater, so there is nothing to ingest and no concentration is
        # defined there. Allowing min_depth == 0 would make the lowest band
        # select dry cells, which is both meaningless and (before the explicit
        # gate in calc_pathogen_conc) produced a risk of 1.0 on dry land.
        if depths[0] <= 0.0:
            raise ValueError(
                f"group {self.name!r}: the lowest depth_threshold must have "
                f"min_depth > 0 (a group cannot be exposed on dry land); got "
                f"{depths[0]}"
            )
        names = [t.name for t in self.depth_thresholds]
        if len(set(names)) != len(names):
            raise ValueError(
                f"group {self.name!r}: depth_threshold names must be unique; "
                f"got {names}"
            )
        return self
