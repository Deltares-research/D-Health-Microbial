from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Base for all d_health config models.

    Immutable (``frozen=True``) so configs can be hashed and shared safely, and
    strict (``extra="forbid"``) so a typo in a TOML key raises rather than
    silently being ignored.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
