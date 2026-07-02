from __future__ import annotations

from pydantic import Field, model_validator

from d_health.config.base import FrozenModel


class PathogenParameters(FrozenModel):
    """Dose-response parameters for a single pathogen.

    The only kernel implemented today is beta-Poisson
    (``risk.calc_infection_risk_beta_poisson``):

        risk = 1 - (1 + dose / beta) ** (-alpha)

    so ``alpha`` and ``beta`` are the only parameters consumed by the model.
    ``source`` is metadata for provenance only. If a second distribution is
    added, re-introduce a discriminator field here and dispatch in ``risk``.
    """

    alpha: float = Field(
        gt=0.0,
        description=(
            "Shape parameter of the beta-Poisson dose-response curve "
            "(dimensionless, > 0). Default E. coli value 0.373 from "
            "Teunis et al. (2008)."
        ),
    )
    beta: float = Field(
        gt=0.0,
        description=(
            "Scale parameter of the beta-Poisson dose-response curve "
            "(dimensionless, > 0). Default E. coli value 39.71 from "
            "Teunis et al. (2008)."
        ),
    )
    source: str = Field(
        default="",
        description=(
            "Free-text citation for the alpha/beta values. Not consumed by "
            "the model; carried for provenance."
        ),
    )


def _default_pathogens() -> dict[str, "PathogenParameters"]:
    """The bundled E. coli catalogue (Teunis et al. 2008), as a default object."""
    return {
        "E.coli": PathogenParameters(
            alpha=0.373,
            beta=39.71,
            source="Teunis et al. (2008)",
        ),
    }


class PathogenConfig(FrozenModel):
    """Catalogue of dose-response parameters plus the one selected for this run.

    Both fields default to the bundled ``E.coli`` entry, so ``PathogenConfig()``
    (or an empty ``[settings.pathogen]``) is a valid config. A config.toml
    overrides ``selected`` and/or supplies
    ``[settings.pathogen.pathogens.<name>]`` entries.

    **Overrides replace the catalogue wholesale.** Because the default is a
    single Python object rather than a deep-merged TOML, declaring *any*
    ``pathogens`` entry in a config.toml replaces the whole catalogue — the bundled
    ``E.coli`` default is dropped unless you restate it.
    """

    selected: str = Field(
        default="E.coli",
        description=(
            "Name of the active pathogen — must be a key in ``pathogens``. "
            "Looked up via the ``active`` property. Defaults to ``E.coli``."
        ),
    )
    pathogens: dict[str, PathogenParameters] = Field(
        default_factory=_default_pathogens,
        description=(
            "Catalogue of available pathogens keyed by name. The entry "
            "matching ``selected`` is what the model actually consumes. "
            "Defaults to the bundled ``E.coli`` entry."
        ),
    )

    @model_validator(mode="after")
    def _check_selected_exists(self) -> "PathogenConfig":
        if self.selected not in self.pathogens:
            raise ValueError(
                f"selected pathogen {self.selected!r} not in pathogens; "
                f"available: {sorted(self.pathogens)}"
            )
        return self

    @property
    def active(self) -> PathogenParameters:
        """The ``PathogenParameters`` for ``selected``."""
        return self.pathogens[self.selected]
